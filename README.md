# Home Assistant Luminus Energy Cost

> **_NOTE:_** Very basic first version hacked together. You should not expect this to work reliably. Currently hardcoded for ComfyFlex, Flanders / Fluvius (Iverelek) and day / night meter.

> **_NOTE:_** It is currently expected that this will break every now and then when Luminus updates their PDF format. In that case the regexes in `sensor.py` need to be updated.

Home Assistant sensors to provide real time energy costs for the Belgian energy provider Luminus. This includes electricity / gas prices.

Electricity prices are returned in €/kWh, gas prices in €/m³. 

## Installation

Clone this repo into the `custom_components` directory:

```sh
cd [HA_HOME]/custom_components
git clone git@github.com:dennisfrett/HomeAssistantLuminusEnergyCost.git luminus_energy_cost
```

## Configuration

Next add the sensor definition:

```yaml
# If you want to debug.
logger:
  default: warning
  logs:
    custom_components.luminus_energy_costs: info

sensor:
    - platform: luminus_energy_cost
      type: elek_dag

    - platform: luminus_energy_cost
      type: elek_nacht

    - platform: luminus_energy_cost
      type: gas
```
