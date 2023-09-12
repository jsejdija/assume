import pandas as pd

from assume.common.base import BaseStrategy, SupportsMinMax
from assume.common.forecasts import CsvForecaster
from assume.common.market_objects import MarketConfig, Order, Orderbook, Product
from assume.units.building import Building
from assume.units.plant import Plant


class NaiveStrategy(BaseStrategy):
    """
    A naive strategy that bids the marginal cost of the unit on the market.
    """

    """
    Methods
    -------
    """

    def calculate_bids(
        self,
        unit: SupportsMinMax,
        market_config: MarketConfig,
        product_tuples: list[Product],
        **kwargs,
    ) -> Orderbook:
        """
        Takes information from a unit that the unit operator manages and
        defines how it is dispatched to the market

        :param unit: the unit to be dispatched
        :type unit: SupportsMinMax
        :param market_config: the market configuration
        :type market_config: MarketConfig
        :param product_tuples: list of all products the unit can offer
        :type product_tuples: list[Product]
        :return: the bids
        :rtype: Orderbook
        """
        start = product_tuples[0][0]  # start time of the first product
        end_all = product_tuples[-1][1]  # end time of the last product
        previous_power = unit.get_output_before(
            start
        )  # power output of the unit before the start time of the first product
        min_power, max_power = unit.calculate_min_max_power(
            start, end_all
        )  # minimum and maximum power output of the unit between the start time of the first product and the end time of the last product

        bids = []
        for product in product_tuples:
            """
            for each product, calculate the marginal cost of the unit at the start time of the product
            and the volume of the product. Dispatch the order to the market.
            """
            start = product[0]
            current_power = unit.outputs["energy"].at[
                start
            ]  # power output of the unit at the start time of the current product
            marginal_cost = unit.calculate_marginal_cost(
                start, previous_power
            )  # calculation of the marginal costs
            volume = unit.calculate_ramp(
                previous_power, max_power[start], current_power
            )
            bids.append(
                {
                    "start_time": product[0],
                    "end_time": product[1],
                    "only_hours": product[2],
                    "price": marginal_cost,
                    "volume": volume,
                }
            )

            previous_power = volume + current_power

        return bids


class NaiveDAStrategy(BaseStrategy):
    def calculate_bids(
        self,
        unit: SupportsMinMax,
        market_config: MarketConfig,
        product_tuples: list[Product],
        **kwargs,
    ) -> Orderbook:
        start = product_tuples[0][0]
        end_all = product_tuples[-1][1]
        previous_power = unit.get_output_before(start)
        min_power, max_power = unit.calculate_min_max_power(start, end_all)

        current_power = unit.outputs["energy"].at[start]
        marginal_cost = unit.calculate_marginal_cost(start, previous_power)
        volume = unit.calculate_ramp(previous_power, max_power[start], current_power)

        profile = {product[0]: volume for product in product_tuples}
        order: Order = {
            "start_time": start,
            "end_time": product_tuples[0][1],
            "only_hours": product_tuples[0][2],
            "price": marginal_cost,
            "volume": profile,
            "accepted_volume": {product[0]: 0 for product in product_tuples},
            "bid_type": "BB",
        }

        bids = [order]
        return bids


class NaiveDABuildingStrategy(BaseStrategy):
    def calculate_bids(
        self,
        unit: SupportsMinMax,
        market_config: MarketConfig,
        product_tuples: list[Product],
        **kwargs,
    ) -> Orderbook:
        # Run the optimization for the building unit
        t = start

        heating_demand = unit.forecaster["heating_demand"]
        cooling_demand = unit.forecaster["cooling_demand"]
        unit.heating_demand = heating_demand
        # print(heating_demand)
        unit.heating_demand = cooling_demand
        unit.run_optimization()

        # Fetch the optimized demand (aggregated_power_in)
        optimized_demand = unit.model.aggregated_power_in.get_values()

        start = product_tuples[0][0]
        end_all = product_tuples[-1][1]

        # Populate product_tuples with optimized demand values
        product_tuples = [(t, optimized_demand[t]) for t in unit.model.time_steps]

        # Calculate the marginal cost based on the optimized demand

        marginal_cost = optimized_demand[t] * unit.calculate_marginal_cost(start=t)

        # Create the profile using optimized_demand
        profile = {product[0]: product[1] for product in product_tuples}

        order: Order = {
            "start_time": start,
            "end_time": end_all,
            "only_hours": product_tuples[0][2],
            "price": marginal_cost,
            "volume": profile,
            "accepted_volume": {product[0]: 0 for product in product_tuples},
            "bid_type": "BB",
        }

        bids = [order]
        return bids


class NaiveDAplantStrategy(BaseStrategy):
    def calculate_bids(
        self,
        unit: Plant,
        market_config: MarketConfig,
        product_tuples: list[Product],
        start: pd.Timestamp = None,
        end: pd.Timestamp = None,
        **kwargs,
    ) -> Orderbook:
        # Run the optimization for the building unit
        t = start

        hydrogen_demand = unit.forecaster.get_heating_demand()
        print(hydrogen_demand)
        unit.hydrogen_demand = hydrogen_demand
        unit.run_optimization()

        # Fetch the optimized demand (aggregated_power_in)
        optimized_demand = unit.model.aggregated_power_in.get_values()

        start = product_tuples[0][0]
        end_all = product_tuples[-1][1]

        # Populate product_tuples with optimized demand values
        product_tuples = [(t, optimized_demand[t]) for t in unit.model.time_steps]

        # Calculate the marginal cost based on the optimized demand

        marginal_cost = (
            optimized_demand[t] * unit.forecaster.get_electricity_price("EOM")[t]
        )

        # Create the profile using optimized_demand
        profile = {product[0]: product[1] for product in product_tuples}

        order: Order = {
            "start_time": start,
            "end_time": end_all,
            "only_hours": product_tuples[0][2],
            "price": marginal_cost,
            "volume": profile,
            "accepted_volume": {product[0]: 0 for product in product_tuples},
            "bid_type": "BB",
        }

        bids = [order]
        return bids


class NaivePosReserveStrategy(BaseStrategy):
    """
    A naive strategy that bids the ramp up volume on the positive reserve market (price = 0).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def calculate_bids(
        self,
        unit: SupportsMinMax,
        market_config: MarketConfig,
        product_tuples: list[Product],
        **kwargs,
    ) -> Orderbook:
        """
        Takes information from a unit that the unit operator manages and
        defines how it is dispatched to the market

        :param unit: the unit to be dispatched
        :type unit: SupportsMinMax
        :param market_config: the market configuration
        :type market_config: MarketConfig
        :param product_tuples: list of all products the unit can offer
        :type product_tuples: list[Product]
        :return: the bids consisting of the start time, end time, only hours, price and volume.
        :rtype: Orderbook
        """

        start = product_tuples[0][0]
        end_all = product_tuples[-1][1]
        previous_power = unit.get_output_before(start)
        min_power, max_power = unit.calculate_min_max_power(
            start, end_all, market_config.product_type
        )

        bids = []
        for product in product_tuples:
            start = product[0]
            current_power = unit.outputs["energy"].at[start]
            volume = unit.calculate_ramp(
                previous_power, max_power[start], current_power
            )
            price = 0
            bids.append(
                {
                    "start_time": product[0],
                    "end_time": product[1],
                    "only_hours": product[2],
                    "price": price,
                    "volume": volume,
                }
            )
            previous_power = volume + current_power
        return bids


class NaiveNegReserveStrategy(BaseStrategy):
    """
    A naive strategy that bids the ramp down volume on the negative reserve market (price = 0).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def calculate_bids(
        self,
        unit: SupportsMinMax,
        market_config: MarketConfig,
        product_tuples: list[Product],
        **kwargs,
    ) -> Orderbook:
        """
        Takes information from a unit that the unit operator manages and
        defines how it is dispatched to the market

        :param unit: the unit to be dispatched
        :type unit: SupportsMinMax
        :param market_config: the market configuration
        :type market_config: MarketConfig
        :param product_tuples: list of all products the unit can offer
        :type product_tuples: list[Product]
        :return: the bids consisting of the start time, end time, only hours, price and volume.
        :rtype: Orderbook
        """
        start = product_tuples[0][0]
        end_all = product_tuples[-1][1]
        previous_power = unit.get_output_before(start)
        min_power, max_power = unit.calculate_min_max_power(
            start, end_all, market_config.product_type
        )

        bids = []
        for product in product_tuples:
            start = product[0]
            previous_power = unit.get_output_before(start)
            current_power = unit.outputs["energy"].at[start]
            volume = unit.calculate_ramp(
                previous_power, min_power[start], current_power
            )
            price = 0
            bids.append(
                {
                    "start_time": product[0],
                    "end_time": product[1],
                    "only_hours": product[2],
                    "price": price,
                    "volume": volume,
                }
            )
            previous_power = volume + current_power
        return bids
