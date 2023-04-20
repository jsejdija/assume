# ASSUME

**ASSUME** is an open-source tool-box for an agent-based simulation 
of the European electricity and later on energy markets with a main
focus on the German market setup. As a newly developed open-source 
model its priority is to ensure usability and customisability 
for a variety of users and use cases in the energy system modelling community. 

The unique feature of the ASSUME tool-box is the integration of **deep reinforcement 
learning** methods into the behavioural strategies of market agents. 
The model comes with different predefined agent representations for the demand and 
generation side that can be used as plug-and-play modules,
which facilitate reinforcement of learning strategies. 
This setup enables a research of new market designs and dynamics in the energy markets.

The project is developed by [developers](https://assume.readthedocs.io/en/latest/developers.html) from INATECH at University of Freiburg, IISM at KIT, Fraunhofer ISI, FH Aachen.
The project ASSUME is funded by the Federal Ministry for Economic
Affairs and Energy (BMWK).

Documentation
=============

[Documentation](https://assume.readthedocs.io/en/latest/)

[Installation](https://assume.readthedocs.io/en/latest/installation.html)


Installation
============

Using conda
-----------

First clone the repository:

```
git clone https://github.com/assume-framework/assume.git
```

Next, navigate to the cloned directory:

```
cd $where you cloned the repo$
```

Now, create a conda environment:

```
conda env create -f environment.yml
```

Afterwards, activate the environment:
```
conda activate assume-framework
```

After these steps you can also run the example simulation:

```
python examples/example_01/main.py
```

Access to database and dashboards
---------------------------------
To save the simulation results to a database and be able to analyze them using Grafan dashboards, install the docker container:

```
docker compose up --build
```

This will start a container for timescaledb and grafana with preconfigured grafana dashboard.

Quick Start
-----------

To run an exemplar simulation without database and grafana, run the following command:
```
    python examples/example_01/example_01.py
```

If you have also built the docker container, run the following command:
```
    python examples/example_02/example_02.py
```

Licence
=======

Copyright 2022-2023 [ASSUME developers](https://assume.readthedocs.io/en/latest/developers.html)

ASSUME is licensed under the [GNU Affero General Public License v3.0](./LICENSE)
