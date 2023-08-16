import logging
from datetime import datetime, timedelta

import pandas as pd
from dateutil import rrule as rr

from assume import World
from assume.common.forecasts import NaiveForecast
from assume.common.market_objects import MarketConfig, MarketProduct

log = logging.getLogger(__name__)

db_uri = "postgresql://assume:assume@localhost:5432/assume"

world = World(database_uri=db_uri)


async def init():
    start = datetime(2023, 10, 4)
    end = datetime(2023, 12, 5)
    index = pd.date_range(
        start=start,
        end=end + timedelta(hours=24),
        freq="H",
    )
    sim_id = "handmade_simulation"

    await world.setup(
        start=start,
        end=end,
        save_frequency_hours=48,
        simulation_id=sim_id,
        index=index,
    )

    marketdesign = [
        MarketConfig(
            "EOM",
            rr.rrule(rr.HOURLY, interval=24, dtstart=start, until=end),
            timedelta(hours=1),
            "pay_as_clear",
            [MarketProduct(timedelta(hours=1), 24, timedelta(hours=1))],
            additional_fields=["block_id", "link", "exclusive_id"],
        )
    ]

    mo_id = "market_operator"
    world.add_market_operator(id=mo_id)
    for market_config in marketdesign:
        world.add_market(mo_id, market_config)

    world.add_unit_operator("my_operator")
    world.add_unit_operator("my_demand")
    world.add_unit(
        "demand1",
        "demand",
        "my_demand",
        # the unit_params have no hints
        {
            "min_power": 0,
            "max_power": 1000,
            "bidding_strategies": {"energy": "naive"},
            "technology": "demand",
        },
        NaiveForecast(index, demand=100),
    )

    nuclear_forecast = NaiveForecast(index, availability=1, fuel_price=3, co2_price=0.1)
    world.add_unit(
        "nuclear1",
        "power_plant",
        "my_operator",
        {
            "min_power": 200,
            "max_power": 1000,
            "bidding_strategies": {"energy": "naive"},
            "technology": "nuclear",
        },
        nuclear_forecast,
    )


world.loop.run_until_complete(init())
world.run()
