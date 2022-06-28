# Nieuwestroom Custom Component voor Home Assistant
Middels deze integratie wordt de huidige prijsinformatie van Nieuwestroom beschikbaar gemaakt binnen Home Assistant.

Deze integratie (inclusief deze readme) is zwaar "geinspireerd" door de [Frank Energie custom component](https://github.com/bajansen/home-assistant-frank_energie) van [@bajansen](https://github.com/bajansen).

De waarden van de prijssensoren kunnen bijvoorbeeld gebruikt worden om apparatuur te schakelen op basis van de huidige energieprijs.

## Installatie
Plaats de map `nieuwestroom` uit de map `custom_components` binnen deze repo in de `custom_components` map van je Home Assistant installatie.

### HACS
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

Installatie via HACS is mogelijk door deze repository toe te voegen als [custom repository](https://hacs.xyz/docs/faq/custom_repositories) met de categorie 'Integratie'.

### Configuratie

De plugin en sensoren worden per stuk geconfigureerd in `configuration.yaml`.

```
sensor:
  - platform: nieuwestroom
    display_options:
      - elec_market
      - elec_min
      - elec_max
      - elec_avg
```