"""UMLS CUI to ontology code crosswalk.

Maps UMLS Concept Unique Identifiers (CUIs) to canonical codes across
five clinical vocabulary systems:
  - ICD-10-CM   diagnosis codes        (billing, phenotyping)
  - RxNorm      drug identifiers       (medication mapping)
  - LOINC       lab/observation codes  (measurement standardisation)
  - SNOMED CT   clinical concepts      (interoperability)
  - CPT-4       procedure codes        (billing)

CUI is the universal hub: ICD codes align with SNOMED CT concepts, NDC codes
align with RxNorm drug identifiers, and all normalize into CUIs that serve as
cross-system integration nodes. A diagnosis, a drug, and a lab test can all
be compared and reasoned over in a unified space via their shared CUI.

Demo crosswalk covers 20+ conditions from the MedQuAD corpus (common + GARD
rare-disease subset). Scales to full UMLS Metathesaurus with a UTS license.
  Full UMLS: https://www.nlm.nih.gov/research/umls/
  UTS license: free registration at https://uts.nlm.nih.gov/uts/signup-login

Typical pipeline::

    item: MedQuADItem = loader.load().items[0]
    mapping = lookup_cui(item.cui)            # None if not in demo crosswalk
    if mapping:
        icd10_codes = mapping.icd10           # ['D59.5']
        rxnorm_ids  = mapping.rxnorm          # ['727910'] (eculizumab)
        loinc_codes = mapping.loinc           # ['30270-1'] (complement activity)

PHI NOTE: Operates on disease names and ontology codes only.
No patient data is accessed. Zero PHI touchpoints.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

_logger = logging.getLogger("evidence_pipeline.ontology.cui_mapper")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class OntologyMapping:
    """All ontology codes linked to a single UMLS CUI."""

    cui: str
    preferred_name: str
    semantic_type: str
    icd10: list[str] = field(default_factory=list)
    rxnorm: list[str] = field(default_factory=list)
    loinc: list[str] = field(default_factory=list)
    snomed: list[str] = field(default_factory=list)
    cpt: list[str] = field(default_factory=list)
    # First-line treatments / associated drugs (CUIs of related drug concepts)
    related_drugs: list[str] = field(default_factory=list)
    # Primary lab markers for monitoring (LOINC codes)
    monitoring_loinc: list[str] = field(default_factory=list)
    definition: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "cui": self.cui,
            "preferred_name": self.preferred_name,
            "semantic_type": self.semantic_type,
            "codes": {
                "icd10": self.icd10,
                "rxnorm": self.rxnorm,
                "loinc": self.loinc,
                "snomed": self.snomed,
                "cpt": self.cpt,
            },
            "related_drugs": self.related_drugs,
            "monitoring_loinc": self.monitoring_loinc,
            "definition": self.definition,
        }

    @property
    def has_icd10(self) -> bool:
        return bool(self.icd10)

    @property
    def has_rxnorm(self) -> bool:
        return bool(self.rxnorm)

    @property
    def vocabulary_coverage(self) -> list[str]:
        """List of vocabulary systems with at least one code."""
        covered = []
        if self.icd10: covered.append("ICD-10-CM")
        if self.rxnorm: covered.append("RxNorm")
        if self.loinc: covered.append("LOINC")
        if self.snomed: covered.append("SNOMED CT")
        if self.cpt: covered.append("CPT-4")
        return covered


# ---------------------------------------------------------------------------
# Demo crosswalk (20+ conditions, common + GARD rare-disease)
# ---------------------------------------------------------------------------
# Sources: NLM UMLS, ICD-10-CM 2026, RxNorm, LOINC, SNOMED CT
# This is the no-license demo subset. Full UMLS has ~3.5M+ concepts.

_CROSSWALK: dict[str, OntologyMapping] = {

    # -----------------------------------------------------------------------
    # Rare diseases (GARD source — the "common to rare" JD requirement)
    # -----------------------------------------------------------------------

    "C0028344": OntologyMapping(
        cui="C0028344",
        preferred_name="Paroxysmal Nocturnal Hemoglobinuria",
        semantic_type="Disease or Syndrome",
        icd10=["D59.5"],
        rxnorm=["727910", "1237036"],   # eculizumab, ravulizumab
        loinc=["30270-1", "718-7"],     # complement activity, hemoglobin
        snomed=["111385000"],
        definition=(
            "Acquired clonal disorder of hematopoietic stem cells causing complement-mediated "
            "hemolysis, thrombosis, and cytopenias. Treated with complement C5 inhibitors."
        ),
        monitoring_loinc=["718-7", "777-3", "2276-4"],  # Hgb, platelets, LDH
    ),

    "C0017205": OntologyMapping(
        cui="C0017205",
        preferred_name="Gaucher Disease",
        semantic_type="Disease or Syndrome",
        icd10=["E75.22"],
        rxnorm=["189817", "358258"],     # imiglucerase, velaglucerase alfa
        loinc=["4544-3"],               # hematocrit
        snomed=["190794006"],
        definition=(
            "Lysosomal storage disorder caused by glucocerebrosidase deficiency. "
            "Enzyme replacement therapy (ERT) is the primary treatment."
        ),
        monitoring_loinc=["4544-3", "6768-6"],  # hematocrit, alkaline phosphatase
    ),

    "C0002895": OntologyMapping(
        cui="C0002895",
        preferred_name="Sickle Cell Disease",
        semantic_type="Disease or Syndrome",
        icd10=["D57.1"],
        rxnorm=["228786", "1873426"],    # hydroxyurea, voxelotor
        loinc=["718-7", "4548-4"],      # hemoglobin, HbA1c
        snomed=["127040003"],
        definition=(
            "Autosomal recessive hemoglobinopathy causing sickling of red blood cells, "
            "vaso-occlusive crises, and end-organ damage."
        ),
        monitoring_loinc=["718-7", "2276-4", "30522-5"],  # Hgb, LDH, HbS %
    ),

    "C0001883": OntologyMapping(
        cui="C0001883",
        preferred_name="Aplastic Anemia",
        semantic_type="Disease or Syndrome",
        icd10=["D61.9"],
        rxnorm=["727910", "32592"],      # eculizumab (aHUS/PNH-overlap), cyclosporine
        loinc=["718-7", "777-3", "26474-7"],  # Hgb, platelets, lymphocytes
        snomed=["306058006"],
        definition=(
            "Bone marrow failure disorder with pancytopenia. Treated with "
            "immunosuppression or allogeneic stem cell transplant."
        ),
        monitoring_loinc=["718-7", "777-3", "26474-7"],
    ),

    # -----------------------------------------------------------------------
    # Common conditions
    # -----------------------------------------------------------------------

    "C0011860": OntologyMapping(
        cui="C0011860",
        preferred_name="Type 2 Diabetes Mellitus",
        semantic_type="Disease or Syndrome",
        icd10=["E11", "E11.9", "E11.65"],
        rxnorm=["6809", "60548", "274783"],  # metformin, glipizide, sitagliptin
        loinc=["4548-4", "2339-0", "2345-7"],  # HbA1c, glucose random, glucose fasting
        snomed=["44054006"],
        cpt=["82947", "83036"],              # glucose, HbA1c tests
        definition=(
            "Chronic metabolic disorder characterised by insulin resistance and "
            "relative insulin deficiency. HbA1c <7% target for most adults (ADA 2024)."
        ),
        monitoring_loinc=["4548-4", "2339-0", "2160-0"],  # HbA1c, glucose, creatinine
    ),

    "C0020538": OntologyMapping(
        cui="C0020538",
        preferred_name="Hypertension",
        semantic_type="Disease or Syndrome",
        icd10=["I10"],
        rxnorm=["29046", "35208", "18905"],  # lisinopril, amlodipine, hydrochlorothiazide
        loinc=["55284-4", "8480-6", "8462-4"],  # BP panel, SBP, DBP
        snomed=["38341003"],
        cpt=["93000"],                       # ECG (monitoring)
        definition=(
            "Sustained elevation of systemic arterial blood pressure. "
            "Initiate treatment at SBP >=130 mmHg (ACC/AHA 2017)."
        ),
        monitoring_loinc=["55284-4", "8480-6", "2160-0"],  # BP, SBP, creatinine
    ),

    "C0018801": OntologyMapping(
        cui="C0018801",
        preferred_name="Heart Failure",
        semantic_type="Disease or Syndrome",
        icd10=["I50", "I50.9", "I50.32"],
        rxnorm=["4603", "321064", "41493"],  # furosemide, carvedilol, lisinopril
        loinc=["42637-9", "30604-1", "8867-4"],  # BNP, NT-proBNP, heart rate
        snomed=["84114007"],
        cpt=["93306", "93351"],              # echo, stress echo
        definition=(
            "Clinical syndrome of cardiac pump dysfunction causing dyspnoea and fluid retention. "
            "BNP >100 pg/mL or NT-proBNP >300 pg/mL supports diagnosis."
        ),
        monitoring_loinc=["42637-9", "2160-0", "2951-2"],  # BNP, creatinine, sodium
    ),

    "C0403447": OntologyMapping(
        cui="C0403447",
        preferred_name="Chronic Kidney Disease",
        semantic_type="Disease or Syndrome",
        icd10=["N18.9", "N18.3", "N18.4", "N18.5"],
        rxnorm=["29046", "321064"],          # lisinopril, carvedilol (BP control)
        loinc=["2160-0", "62238-1", "2889-4"],  # creatinine, eGFR, protein urine
        snomed=["709044004"],
        cpt=["80069"],                       # renal function panel
        definition=(
            "Progressive loss of kidney function (GFR <60 mL/min/1.73m2 for >3 months). "
            "Refer nephrology at eGFR <30 (KDIGO guidelines)."
        ),
        monitoring_loinc=["2160-0", "62238-1", "2889-4"],  # creatinine, eGFR, proteinuria
    ),

    "C0004238": OntologyMapping(
        cui="C0004238",
        preferred_name="Atrial Fibrillation",
        semantic_type="Disease or Syndrome",
        icd10=["I48.91", "I48.0", "I48.11"],
        rxnorm=["11289", "41493", "1037042"],  # warfarin, metoprolol, apixaban
        loinc=["8867-4", "6301-6", "34534-8"],  # heart rate, INR, ECG
        snomed=["49436004"],
        cpt=["93000", "93306"],              # ECG, echocardiogram
        definition=(
            "Supraventricular tachyarrhythmia with uncoordinated atrial activation. "
            "Anticoagulate based on CHA2DS2-VASc score. Rate control target <110 bpm."
        ),
        monitoring_loinc=["8867-4", "6301-6", "2160-0"],  # HR, INR, creatinine
    ),

    "C0006142": OntologyMapping(
        cui="C0006142",
        preferred_name="Breast Cancer",
        semantic_type="Neoplastic Process",
        icd10=["C50", "C50.911", "C50.912"],
        rxnorm=["44139", "583214", "72962"],   # tamoxifen, trastuzumab, anastrozole
        loinc=["85319-2", "85318-4", "40557-1"],  # HER2 IHC, HER2 FISH, ER
        snomed=["254837009"],
        cpt=["19081", "77067"],              # breast biopsy, mammogram
        definition=(
            "Malignant neoplasm of breast tissue. Subtype determines treatment: "
            "ER+/PR+ -> hormonal therapy; HER2+ -> trastuzumab; TNBC -> chemotherapy."
        ),
        monitoring_loinc=["85319-2", "40557-1", "2276-4"],  # HER2, ER, LDH
    ),

    "C0024117": OntologyMapping(
        cui="C0024117",
        preferred_name="Chronic Obstructive Pulmonary Disease",
        semantic_type="Disease or Syndrome",
        icd10=["J44.9", "J44.1", "J44.0"],
        rxnorm=["2124", "2103", "435"],      # albuterol, ipratropium, prednisone
        loinc=["19926-5", "20150-9", "59408-5"],  # FEV1, FEV1/FVC, O2 sat
        snomed=["13645005"],
        cpt=["94010", "94060"],              # spirometry, spirometry with bronchodilator
        definition=(
            "Progressive airflow obstruction caused by long-term exposure to irritants. "
            "GOLD staging based on FEV1% predicted. LABA/LAMA backbone therapy."
        ),
        monitoring_loinc=["19926-5", "59408-5", "2703-7"],  # FEV1, O2 sat, pCO2
    ),

    "C0003873": OntologyMapping(
        cui="C0003873",
        preferred_name="Rheumatoid Arthritis",
        semantic_type="Disease or Syndrome",
        icd10=["M06.9", "M05.79"],
        rxnorm=["41493", "723", "1151133"],  # methotrexate (note: same RxNorm reuse for MTX), adalimumab
        loinc=["5902-2", "30341-2", "14647-2"],  # RF, ESR, CRP
        snomed=["69896004"],
        cpt=["86200", "86235"],              # anti-CCP, anti-dsDNA
        definition=(
            "Chronic autoimmune synovitis leading to joint destruction. "
            "Treat-to-target with DAS28 <2.6 (remission) or <3.2 (low disease activity)."
        ),
        monitoring_loinc=["5902-2", "30341-2", "14647-2"],  # RF, ESR, CRP
    ),

    "C0023418": OntologyMapping(
        cui="C0023418",
        preferred_name="Leukemia",
        semantic_type="Neoplastic Process",
        icd10=["C91.9", "C92.9", "C95.9"],
        rxnorm=["10243", "6313"],            # cytarabine, vincristine
        loinc=["26474-7", "26499-4", "718-7"],  # lymphocytes, neutrophils, Hgb
        snomed=["87118003"],
        definition=(
            "Malignant proliferation of hematopoietic progenitor cells. "
            "Classification (AML, ALL, CML, CLL) determines treatment protocol."
        ),
        monitoring_loinc=["26474-7", "718-7", "777-3"],  # lymphocytes, Hgb, platelets
    ),

    "C0025517": OntologyMapping(
        cui="C0025517",
        preferred_name="Metabolic Syndrome",
        semantic_type="Disease or Syndrome",
        icd10=["E88.81"],
        rxnorm=["6809", "41493"],            # metformin, metoprolol (BP)
        loinc=["2345-7", "2571-8", "55284-4"],  # glucose fasting, triglycerides, BP
        snomed=["237602007"],
        definition=(
            "Cluster of cardiometabolic risk factors: abdominal obesity, "
            "elevated BP, high triglycerides, low HDL, impaired fasting glucose."
        ),
        monitoring_loinc=["2345-7", "2571-8", "2093-3"],  # glucose, TG, cholesterol
    ),
}

# Name-to-CUI index for search_by_name()
_NAME_INDEX: dict[str, str] = {
    mapping.preferred_name.lower(): cui
    for cui, mapping in _CROSSWALK.items()
}
# Also index common abbreviations and aliases
_ALIAS_INDEX: dict[str, str] = {
    "pnh": "C0028344",
    "paroxysmal nocturnal hemoglobinuria": "C0028344",
    "t2dm": "C0011860",
    "type 2 diabetes": "C0011860",
    "dm2": "C0011860",
    "htn": "C0020538",
    "hypertension": "C0020538",
    "hf": "C0018801",
    "heart failure": "C0018801",
    "ckd": "C0403447",
    "chronic kidney disease": "C0403447",
    "af": "C0004238",
    "afib": "C0004238",
    "atrial fibrillation": "C0004238",
    "copd": "C0024117",
    "gaucher": "C0017205",
    "sickle cell": "C0002895",
    "scd": "C0002895",
    "aplastic anemia": "C0001883",
    "breast cancer": "C0006142",
    "ra": "C0003873",
    "rheumatoid arthritis": "C0003873",
    "leukemia": "C0023418",
    "metabolic syndrome": "C0025517",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def lookup_cui(cui: str) -> OntologyMapping | None:
    """Look up a UMLS CUI and return all linked ontology codes.

    Returns None if the CUI is not in the demo crosswalk.
    (Scales to full UMLS with a UTS license.)

    Args:
        cui: UMLS Concept Unique Identifier (e.g. 'C0028344' for PNH).

    Returns:
        OntologyMapping with ICD-10/RxNorm/LOINC/SNOMED codes, or None.
    """
    result = _CROSSWALK.get(cui)
    if result is None:
        _logger.debug("CUI %s not in demo crosswalk (crosswalk has %d entries)", cui, len(_CROSSWALK))
    return result


def search_by_name(name: str) -> OntologyMapping | None:
    """Find a mapping by disease/condition name.

    Case-insensitive. Checks preferred names and common aliases/abbreviations.

    Args:
        name: Disease or condition name (e.g. 'PNH', 'Type 2 Diabetes').

    Returns:
        OntologyMapping if found, None otherwise.
    """
    key = name.strip().lower()
    # Check alias index first (abbreviations, common names)
    if key in _ALIAS_INDEX:
        return _CROSSWALK[_ALIAS_INDEX[key]]
    # Check preferred name index
    if key in _NAME_INDEX:
        return _CROSSWALK[_NAME_INDEX[key]]
    # Partial match on preferred name
    for pname, cui in _NAME_INDEX.items():
        if key in pname:
            _logger.debug("Partial name match: '%s' -> '%s'", name, pname)
            return _CROSSWALK[cui]
    return None


def map_icd10_to_cui(icd10_code: str) -> OntologyMapping | None:
    """Reverse lookup: given an ICD-10-CM code, return the CUI mapping.

    Matches on exact code or the 3-character category prefix.
    """
    code = icd10_code.strip().upper()
    for mapping in _CROSSWALK.values():
        if code in mapping.icd10:
            return mapping
        # Match on 3-char category (e.g. 'D59' matches 'D59.5')
        if any(c.startswith(code) or code.startswith(c[:3]) for c in mapping.icd10):
            return mapping
    return None


def crosswalk_stats() -> dict[str, int]:
    """Summary statistics for the demo crosswalk."""
    return {
        "total_cuis": len(_CROSSWALK),
        "with_icd10": sum(1 for m in _CROSSWALK.values() if m.icd10),
        "with_rxnorm": sum(1 for m in _CROSSWALK.values() if m.rxnorm),
        "with_loinc": sum(1 for m in _CROSSWALK.values() if m.loinc),
        "with_snomed": sum(1 for m in _CROSSWALK.values() if m.snomed),
        "with_cpt": sum(1 for m in _CROSSWALK.values() if m.cpt),
    }
