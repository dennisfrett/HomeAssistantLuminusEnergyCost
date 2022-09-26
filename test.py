import sensor
import re
import sys
import logging

elek_dag = sensor.LuminusEnergyCost("elek_dag", None)
elek_dag.update()

print("Kost elek dag: " + elek_dag.state)

elek_nacht = sensor.LuminusEnergyCost("elek_nacht", None)
elek_nacht.update()


print("Kost elek nacht: " + elek_nacht.state)

gas = sensor.LuminusEnergyCost("gas", None)
gas.update()


print("Kost gas: " + gas.state)

elek_nacht.update()
elek_dag.update()
gas.update()