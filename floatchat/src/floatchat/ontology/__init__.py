"""FloatChat Domain Ontology — the single source of truth for Argo domain knowledge.

Ontology 2.0 (Phase 1 — Domain Ontology Foundation).

This package centralizes the domain vocabulary that was previously fragmented
across the intent parser, fuzzy matcher, query normalizer, classifier,
visualization engine, floats service, query-engine helpers/executors, data
lake, ETL builders, and scientific-explanation features:

* :mod:`floatchat.ontology.variables` — canonical Argo variables: aliases,
  parser synonyms, display titles, units, typo corrections, normalizer terms.
* :mod:`floatchat.ontology.regions` — canonical ocean regions: aliases,
  polygons, bounding boxes, India deployment constants, region tagging.
* :mod:`floatchat.ontology.sensors` — canonical sensors, profiler platform
  models, manufacturers, DAC names, Argo network vocabulary.
* :mod:`floatchat.ontology.intents` — canonical intent vocabulary descriptions
  and the named intent groupings shared across the pipeline.
* :mod:`floatchat.ontology.concepts` — canonical scientific concept glossary.

Design rules:

1. **Pure data, zero dependencies.** Ontology modules import nothing from the
   rest of ``floatchat``. Any module may safely import the ontology.
2. **Behaviour-neutral relocation.** Every constant here was moved verbatim
   from its previous home; consumers import it back. Where two legacy lists
   were similar-but-not-identical (different detection surfaces), both were
   preserved — the ontology records the canonical knowledge and each consumer
   keeps its own policy surface. Nothing in this package changes application
   behavior by itself.
3. **Typed definitions.** Each domain entity is a frozen dataclass so future
   phases can rely on a stable, documented shape.
"""

from floatchat.ontology.concepts import CONCEPTS, ScientificConcept
from floatchat.ontology.intents import (
    FLOAT_CENTRIC_INTENTS,
    INTENT_DEFINITIONS,
    NON_DATA_INTENTS,
    RESPONSE_INTENT_DEFINITIONS,
    SCIENTIFIC_CONTEXT_INTENTS,
    SCIENTIFIC_FOLLOWUP_INTENTS,
    IntentDefinition,
)
from floatchat.ontology.regions import (
    INDIA_DEPLOYMENT_BBOX,
    INDIA_QUERY_REGIONS,
    OCEAN_REGION_PLACE_NAMES,
    REGIONS,
    RegionDefinition,
    point_in_region,
    tag_india_region,
)
from floatchat.ontology.sensors import (
    BGC_VARIABLE_MARKER_TOKENS,
    DAC_NAMES,
    NETWORK_BGC,
    NETWORK_CORE,
    PLATFORM_MODELS,
    SENSORS,
    PlatformModel,
    SensorDefinition,
    manufacturer_short_lookup,
    platform_lookup,
    platform_shortlist,
    sensor_keywords_map,
)
from floatchat.ontology.variables import (
    CATALOGUE_VARIABLE_ORDER,
    LEVELS_VARIABLE_ORDER,
    NORMALIZER_ABBREVIATIONS,
    NORMALIZER_CANONICAL_TERMS,
    PARSER_VARIABLE_ORDER,
    TYPO_CORRECTIONS,
    VARIABLES,
    VariableDefinition,
)

__all__ = [
    # variables
    "VARIABLES",
    "VariableDefinition",
    "PARSER_VARIABLE_ORDER",
    "LEVELS_VARIABLE_ORDER",
    "CATALOGUE_VARIABLE_ORDER",
    "TYPO_CORRECTIONS",
    "NORMALIZER_CANONICAL_TERMS",
    "NORMALIZER_ABBREVIATIONS",
    # regions
    "REGIONS",
    "RegionDefinition",
    "INDIA_QUERY_REGIONS",
    "INDIA_DEPLOYMENT_BBOX",
    "OCEAN_REGION_PLACE_NAMES",
    "point_in_region",
    "tag_india_region",
    # sensors
    "SENSORS",
    "SensorDefinition",
    "PLATFORM_MODELS",
    "PlatformModel",
    "platform_lookup",
    "platform_shortlist",
    "manufacturer_short_lookup",
    "sensor_keywords_map",
    "BGC_VARIABLE_MARKER_TOKENS",
    "NETWORK_CORE",
    "NETWORK_BGC",
    "DAC_NAMES",
    # intents
    "INTENT_DEFINITIONS",
    "RESPONSE_INTENT_DEFINITIONS",
    "IntentDefinition",
    "NON_DATA_INTENTS",
    "SCIENTIFIC_CONTEXT_INTENTS",
    "SCIENTIFIC_FOLLOWUP_INTENTS",
    "FLOAT_CENTRIC_INTENTS",
    # concepts
    "CONCEPTS",
    "ScientificConcept",
]
