# SPDX-FileCopyrightText: Florian Maurer
#
# SPDX-License-Identifier: Apache-2.0

import logging
import time
from importlib import reload
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

db_uri = "postgresql://assume:assume@localhost:5432/assume"
engine = create_engine(db_uri)

scenario = "Germany2019"  # "Simple", "Germany2019", "Austria2019"
run_amiris = False
run_assume = True

scenario_path = f"../amiris-examples/{scenario}"

if run_amiris:
    from amirispy.scripts import amiris_cli

    amiris_path = Path("./amiris-core_*-jar-with-dependencies.jar")
    amiris_paths = list(Path(amiris_path.parent).glob(amiris_path.name))

    if not amiris_paths:
        amiris_cli(["install", "-m", "model"])
        amiris_paths = list(Path(amiris_path.parent).glob(amiris_path.name))
    if not amiris_paths or not amiris_paths[0].is_file():
        print("could not download amiris")

    print(f"running {scenario}")
    start = time.time()
    executable = amiris_paths[0].name
    amiris_cli(
        f"run --jar ./{executable} -s {scenario_path}/scenario.yaml --output scenario/{scenario}".split(
            " "
        )
    )
    duration = time.time() - start
    print(f"took {duration} seconds")

    schema_name = f"amiris_{scenario.lower()}"
    query = text(f"create schema if not exists {schema_name}")
    with engine.begin() as conn:
        conn.execute(query)

    for output_file in (Path("scenario") / scenario).glob("*.csv"):
        with open(output_file, "r") as f:
            df = pd.read_csv(f, sep=";", index_col="TimeStep", parse_dates=["TimeStep"])
        table_name = output_file.stem.lower()
        table_name = table_name[:63]
        with engine.begin() as conn:
            df.to_sql(table_name, conn, if_exists="replace", schema=schema_name)

    print("successfully wrote to sql")
    # kill logging from previous amiris run
    logging.disable(logging.NOTSET)
    reload(logging)

# now start the fresh assume run
if run_assume:
    from assume import World
    from assume.scenario.loader_amiris import load_amiris_async

    forecast_file = Path("scenario", scenario, "MeritOrderForecaster.csv")
    with open(forecast_file, "r") as f:
        forecast = pd.read_csv(
            f, sep=";", index_col="TimeStep", parse_dates=["TimeStep"]
        )

    with open("../amiris-examples/Germany2019/timeseries/co2_price.csv", "r") as f:
        co2 = pd.read_csv(
            f,
            sep=";",
            index_col=0,
            parse_dates=[0],
            header=None,
            date_format="%Y-%m-%d_%H:%M:%S",
        )

    # forecast["ElectricityPriceForecastInEURperMWH"].plot()
    # co2.plot()

    print(f"running {scenario}")
    start = time.time()

    world = World(database_uri=db_uri)
    # world.forecast_price = forecast["ElectricityPriceForecastInEURperMWH"]
    world.loop.run_until_complete(
        load_amiris_async(
            world,
            "amiris",
            scenario.lower(),
            scenario_path,
        )
    )
    world.run()
    duration = time.time() - start
    print(f"took {duration} seconds")
