from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import torch as th

from assume.common.base import LearningStrategy, SupportsMinMax
from assume.common.market_objects import MarketConfig, Orderbook, Product
from assume.common.utils import get_products_index
from assume.reinforcement_learning.learning_utils import Actor, NormalActionNoise


class RLStrategyBlocks(LearningStrategy):
    """
    Reinforcement Learning Strategy

    :param foresight: Number of time steps to look ahead. Default 24.
    :type foresight: int
    :param max_bid_price: Maximum bid price
    :type max_bid_price: float
    :param max_demand: Maximum demand
    :type max_demand: float
    :param device: Device to run on
    :type device: str
    :param float_type: Float type to use
    :type float_type: str
    :param learning_mode: Whether to use learning mode
    :type learning_mode: bool
    :param actor: Actor network
    :type actor: torch.nn.Module
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.unit_id = kwargs["unit_id"]

        # defines bounds of actions space
        self.max_bid_price = kwargs.get("max_bid_price", 100)
        self.max_demand = kwargs.get("max_demand", 10e3)

        # tells us whether we are training the agents or just executing per-learnind stategies
        self.learning_mode = kwargs.get("learning_mode", False)

        # sets the devide of the actor network
        device = kwargs.get("device", "cpu")
        self.device = th.device(device if th.cuda.is_available() else "cpu")
        if not self.learning_mode:
            self.device = th.device("cpu")

        # future: add option to choose between float16 and float32
        # float_type = kwargs.get("float_type", "float32")
        self.float_type = th.float

        # for definition of observation space
        self.foresight = kwargs.get("foresight", 24)

        # define used order types
        self.order_types = kwargs.get("order_types", ["SB"])

        if self.learning_mode:
            self.learning_role = None
            self.collect_initial_experience_mode = kwargs.get(
                "episodes_collecting_initial_experience", True
            )

            self.action_noise = NormalActionNoise(
                mu=0.0,
                sigma=kwargs.get("noise_sigma", 0.1),
                action_dimension=self.act_dim,
                scale=kwargs.get("noise_scale", 1.0),
                dt=kwargs.get("noise_dt", 1.0),
            )

        elif Path(load_path=kwargs["trained_actors_path"]).is_dir():
            self.load_actor_params(load_path=kwargs["trained_actors_path"])

    def calculate_bids(
        self,
        unit: SupportsMinMax,
        market_config: MarketConfig,
        product_tuples: list[Product],
        **kwargs,
    ) -> Orderbook:
        """
        Calculate bids for a unit

        :param unit: Unit to calculate bids for
        :type unit: SupportsMinMax
        :param market_config: Market configuration
        :type market_config: MarketConfig
        :param product_tuples: Product tuples
        :type product_tuples: list[Product]
        :return: Bids containing start time, end time, price and volume
        :rtype: Orderbook
        """

        start = product_tuples[0][0]
        end = product_tuples[-1][1]

        previous_power = unit.get_output_before(start)
        min_power, max_power = unit.calculate_min_max_power(start, end)

        # =============================================================================
        # 1. Get the Observations, which are the basis of the action decision
        # =============================================================================
        next_observation = self.create_observation(
            unit=unit,
            start=start,
            end=end,
        )

        # =============================================================================
        # 2. Get the Actions, based on the observations
        # =============================================================================
        actions, noise = self.get_actions(next_observation)

        # =============================================================================
        # 3. Transform Actions into bids
        # =============================================================================
        # actions are in the range [-1,1], we need to transform them into actual bids
        # we can use our domain knowledge to guide the bid formulation

        bid_price_1 = actions[0].item() * self.max_bid_price
        bid_price_2 = actions[1].item() * self.max_bid_price

        bid_price_inflex = min(bid_price_1, bid_price_2)
        bid_price_flex = max(bid_price_1, bid_price_2)

        # calculate the quantities and transform the bids into orderbook format
        bids = []
        bid_quantity_block = {}
        op_time = unit.get_operation_time(start)

        for product in product_tuples:
            start = product[0]
            end = product[1]

            bid_quantity_inflex = 0
            bid_quantity_flex = 0

            current_power = unit.outputs["energy"].at[start]

            # get technical bounds for the unit output from the unit
            # adjust for ramp speed
            max_power[start] = unit.calculate_ramp(
                op_time, previous_power, max_power[start], current_power
            )
            # adjust for ramp speed
            min_power[start] = unit.calculate_ramp(
                op_time, previous_power, min_power[start], current_power
            )

            # 3.1 formulate the bids for Pmin
            bid_quantity_inflex = min_power[start]

            # 3.1 formulate the bids for Pmax - Pmin
            # Pmin, the minium run capacity is the inflexible part of the bid, which should always be accepted

            if op_time <= -unit.min_down_time or op_time > 0:
                bid_quantity_flex = max_power[start] - bid_quantity_inflex

            if "BB" in self.order_types:
                bid_quantity_block[start] = bid_quantity_inflex

            # actually formulate bids in orderbook format
            # if LB is in order_types, then formulate the linked bid depending on the block bid
            # TODO:what if LB in order_types but not BB?
            if "LB" in self.order_types and bid_quantity_inflex != 0:
                bids.append(
                    {
                        "start_time": start,
                        "end_time": end,
                        "only_hours": None,
                        "price": bid_price_flex,
                        "volume": {start: bid_quantity_flex},
                        "bid_type": "LB",
                        "parent_bid_id": unit.id + "_block",
                    },
                )
            # otherwise just add the flex bid as SB
            else:
                bids.append(
                    {
                        "start_time": start,
                        "end_time": end,
                        "only_hours": None,
                        "price": bid_price_flex,
                        "volume": bid_quantity_flex,
                        "bid_type": "SB",
                    },
                )
            # if no BB in order_types, then also add the inflex bid as SB
            if self.order_types == ["SB"]:
                bids.append(
                    {
                        "start_time": start,
                        "end_time": end,
                        "only_hours": None,
                        "price": bid_price_inflex,
                        "volume": bid_quantity_inflex,
                        "bid_type": "SB",
                    },
                )

            # calculate previous power with planned dispatch (bid_quantity)
            previous_power = bid_quantity_inflex + bid_quantity_flex + current_power
            op_time = max(op_time, 0) + 1 if previous_power > 0 else min(op_time, 0) - 1
            # store results in unit outputs which are written to database by unit operator
            unit.outputs["rl_observations"][start] = next_observation
            unit.outputs["rl_actions"][start] = actions
            unit.outputs["rl_exploration_noise"][start] = noise

        if "BB" in self.order_types:
            bids.append(
                {
                    "start_time": product_tuples[0][0],
                    "end_time": product_tuples[-1][1],
                    "only_hours": product_tuples[0][2],
                    "price": bid_price_inflex,
                    "volume": bid_quantity_block,
                    "bid_type": "BB",
                    "min_acceptance_ratio": 1,
                    "accepted_volume": {product[0]: 0 for product in product_tuples},
                    "bid_id": unit.id + "_block",
                }
            )

        return bids

    def get_actions(self, next_observation):
        """
        Get actions

        :param next_observation: Next observation
        :type next_observation: torch.Tensor
        :return: Actions
        :rtype: torch.Tensor
        """

        # distinction wethere we are in learning mode or not to handle exploration realised with noise
        if self.learning_mode:
            # if we are in learning mode the first x episodes we want to explore the entire action space
            # to get a good initial experience, in the area around the costs of the agent
            if self.collect_initial_experience_mode:
                # define current action as soley noise
                noise = (
                    th.normal(
                        mean=0.0, std=0.2, size=(1, self.act_dim), dtype=self.float_type
                    )
                    .to(self.device)
                    .squeeze()
                )

                # =============================================================================
                # 2.1 Get Actions and handle exploration
                # =============================================================================
                base_bid = next_observation[-1]

                # add noise to the last dimension of the observation
                # needs to be adjusted if observation space is changed, because only makes sense
                # if the last dimension of the observation space are the marginal cost
                curr_action = noise + base_bid.clone().detach()

            else:
                # if we are not in the initial exploration phase we chose the action with the actor neuronal net
                # and add noise to the action
                curr_action = self.actor(next_observation).detach()
                noise = th.tensor(
                    self.action_noise.noise(), device=self.device, dtype=self.float_type
                )
                curr_action += noise
        else:
            # if we are not in learning mode we just use the actor neuronal net to get the action without adding noise

            curr_action = self.actor(next_observation).detach()
            noise = tuple(0 for _ in range(self.act_dim))

        curr_action = curr_action.clamp(-1, 1)

        return curr_action, noise

    def create_observation(
        self,
        unit: SupportsMinMax,
        start: datetime,
        end: datetime,
    ):
        """
        Create observation

        :param unit: Unit to create observation for
        :type unit: SupportsMinMax
        :param start: Start time
        :type start: datetime
        :param end: End time
        :type end: datetime
        :return: Observation
        :rtype: torch.Tensor"""
        end_excl = end - unit.index.freq

        # get the forecast length depending on the time unit considered in the modelled unit
        forecast_len = pd.Timedelta((self.foresight - 1) * unit.index.freq)

        # =============================================================================
        # 1.1 Get the Observations, which are the basis of the action decision
        # =============================================================================
        scaling_factor_res_load = self.max_demand

        # price forecast
        scaling_factor_price = self.max_bid_price

        # total capacity and marginal cost
        scaling_factor_total_capacity = unit.max_power

        # marginal cost
        # Obs[2*foresight+1:2*foresight+2]
        scaling_factor_marginal_cost = self.max_bid_price

        # checks if we are at end of simulation horizon, since we need to change the forecast then
        # for residual load and price forecast and scale them
        product_len = (end - start) / unit.index.freq
        if end_excl + forecast_len > unit.forecaster["residual_load_EOM"].index[-1]:
            scaled_res_load_forecast = (
                unit.forecaster["residual_load_EOM"][
                    -int(product_len + self.foresight - 1) :
                ].values
                / scaling_factor_res_load
            )

        else:
            scaled_res_load_forecast = (
                unit.forecaster["residual_load_EOM"]
                .loc[start : end_excl + forecast_len]
                .values
                / scaling_factor_res_load
            )

        if end_excl + forecast_len > unit.forecaster["price_EOM"].index[-1]:
            scaled_price_forecast = (
                unit.forecaster["price_EOM"][
                    -int(product_len + self.foresight - 1) :
                ].values
                / scaling_factor_price
            )

        else:
            scaled_price_forecast = (
                unit.forecaster["price_EOM"].loc[start : end_excl + forecast_len].values
                / scaling_factor_price
            )

        # get last accepted bid volume and the current marginal costs of the unit
        current_volume = unit.get_output_before(start)

        current_costs = unit.calculate_marginal_cost(start, current_volume)

        # scale unit outpus
        scaled_max_power = current_volume / scaling_factor_total_capacity
        scaled_marginal_cost = current_costs / scaling_factor_marginal_cost

        # calculate the time the unit has to continue to run or be down
        op_time = unit.get_operation_time(start)
        if op_time > 0:
            must_run_time = max(op_time - unit.min_operating_time, 0)
        elif op_time < 0:
            must_run_time = min(op_time + unit.min_down_time, 0)
        scaling_factor_must_run_time = max(unit.min_operating_time, unit.min_down_time)

        scaled_must_run_time = must_run_time / scaling_factor_must_run_time

        # concat all obsverations into one array
        observation = np.concatenate(
            [
                scaled_res_load_forecast,
                scaled_price_forecast,
                np.array(
                    [scaled_must_run_time, scaled_max_power, scaled_marginal_cost]
                ),
            ]
        )

        # transfer arry to GPU for NN processing
        observation = (
            th.tensor(observation, dtype=self.float_type)
            .to(self.device, non_blocking=True)
            .view(-1)
        )

        return observation.detach().clone()

    def calculate_reward(
        self,
        unit,
        marketconfig: MarketConfig,
        orderbook: Orderbook,
    ):
        """
        Calculate reward

        :param unit: Unit to calculate reward for
        :type unit: SupportsMinMax
        :param marketconfig: Market configuration
        :type marketconfig: MarketConfig
        :param orderbook: Orderbook
        :type orderbook: Orderbook
        """

        # =============================================================================
        # 4. Calculate Reward
        # =============================================================================
        # function is called after the market is cleared and we get the market feedback,
        # so we can calculate the profit

        product_type = marketconfig.product_type
        products_index = get_products_index(orderbook, marketconfig)

        max_power = unit.forecaster.get_availability(unit.id)[products_index] * unit.max_power

        constraints_cost = pd.Series(0.0, index=products_index)
        profit = pd.Series(0.0, index=products_index)
        reward = pd.Series(0.0, index=products_index)
        opportunity_cost = pd.Series(0.0, index=products_index)
        costs = pd.Series(0.0, index=products_index)

        # iterate over all orders in the orderbook, to calculate order specific profit
        for order in orderbook:
            start = order["start_time"]
            end = order["end_time"]
            end_excl = end - unit.index.freq

            order_times = pd.date_range(start, end_excl, freq=unit.index.freq)

            # calculate profit as income - running_cost from this event

            for start in order_times:
                marginal_cost = unit.calculate_marginal_cost(
                    start, unit.outputs[product_type].loc[start]
                )
                if isinstance(order["accepted_volume"], dict):
                    accepted_volume = order["accepted_volume"][start]
                else:
                    accepted_volume = order["accepted_volume"]

                if isinstance(order["accepted_price"], dict):
                    accepted_price = order["accepted_price"][start]
                else:
                    accepted_price = order["accepted_price"]

                price_difference = accepted_price - marginal_cost
                
                # calculate opportunity cost
                # as the loss of income we have because we are not running at full power
                order_opportunity_cost = price_difference * (
                    max_power[start] - unit.outputs[product_type].loc[start]
                )
                # if our opportunity costs are negative, we did not miss an opportunity to earn money and we set them to 0
                # don't consider opportunity_cost more than once! Always the same for one timestep and one market
                opportunity_cost[start] = max(order_opportunity_cost, 0)
                profit[start] += accepted_price * accepted_volume
                

        # consideration of start-up costs, which are evenly divided between the
        # upward and downward regulation events
        for start in products_index:
            op_time = unit.get_operation_time(start)
            
            marginal_cost = unit.calculate_marginal_cost(
                start, unit.outputs[product_type].loc[start]
            )
            costs[start] += marginal_cost * unit.outputs[product_type].loc[start]

            if unit.outputs[product_type].loc[start] != 0 and op_time < 0:
                start_up_cost = unit.get_starting_costs(op_time)
                costs[start] += start_up_cost

        # ---------------------------
        # 4.1 Calculate Reward
        # The straight forward implemntation would be reward = profit, yet we would like to give the agent more guidance
        # in the learning process, so we add a regret term to the reward, which is the opportunity cost
        # define the reward and scale it
        
        profit += -costs
        scaling = 1 / (unit.max_power * self.max_bid_price)
        regret_scale = 0.0
        reward = (
            profit - regret_scale * (opportunity_cost + constraints_cost)
        ) * scaling

        # store results in unit outputs which are written to database by unit operator
        unit.outputs["profit"].loc[products_index] = profit
        unit.outputs["reward"].loc[products_index] = reward
        unit.outputs["regret"].loc[products_index] = opportunity_cost
        unit.outputs["total_cost"].loc[products_index] = costs


    def load_actor_params(self, load_path):
        """
        Load actor parameters

        :param simulation_id: Simulation ID
        :type simulation_id: str
        """
        directory = f"{load_path}/actors/actor_{self.unit_id}.pt"

        params = th.load(directory, map_location=self.device)

        self.actor = Actor(self.obs_dim, self.act_dim, self.float_type)
        self.actor.load_state_dict(params["actor"])

        if self.learning_mode:
            self.actor_target = Actor(self.obs_dim, self.act_dim, self.float_type)
            self.actor_target.load_state_dict(params["actor_target"])
            self.actor_target.eval()
            self.actor.optimizer.load_state_dict(params["actor_optimizer"])
