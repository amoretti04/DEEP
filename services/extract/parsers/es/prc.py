"""Parser for Registro Público Concursal (Spain) — BOE Sección IV edictos.

BOE publishes insolvency declarations (concursos de acreedores, aperturas
de liquidación, comunicaciones 5bis preconcurso) in Sección IV of the
daily gazette. The BOE offers a daily XML bundle (bolsa-legislativa) —
we parse the edicto nodes within.

Field names mirror the BOE XSD. As with BODACC, this is a bulk XML
source: one file, many records.
"""

from __future__ import annotations

from typing import Any

from libs.taxonomy import map_proceeding_type
from services.extract.framework import (
    DeclarativeXmlBulkParser,
    ExtractionConfig,
    FieldConfig,
    FieldType,
    RecordPath,
)
from services.extract.framework.config import PIITag


BOE_TYPE_TO_LABEL: dict[str, str] = {
    "CA": "Concurso de acreedores",
    "CC": "Concurso con convenio",
    "CL": "Concurso en liquidación",
    "PC": "Preconcurso",
    "5B": "Comunicación del artículo 5 bis",
    "PR": "Plan de reestructuración",
}


class PrcParser(DeclarativeXmlBulkParser):
    """BOE Sección IV — Registro Público Concursal edictos parser."""

    PARSER_ID = "parsers.es.prc_v1"
    VERSION = "1.0.0"
    records_xpath = "/sumario/diario/seccion[@num='4']/departamento/epigrafe/item"

    config = ExtractionConfig(
        content_type="xml",
        record=RecordPath(
            fields={
                "edicto_id": FieldConfig(
                    type=FieldType.STRING,
                    xpath="./identificador/text()",
                    required=True,
                ),
                "publication_date": FieldConfig(
                    type=FieldType.DATE,
                    xpath="./fecha_publicacion/text()",
                    required=True,
                    date_format="%Y-%m-%d",
                ),
                "court_name": FieldConfig(
                    type=FieldType.STRING,
                    xpath="./juzgado/text()",
                    required=True,
                ),
                "court_case_number": FieldConfig(
                    type=FieldType.STRING,
                    xpath="./numero_autos/text()",
                    required=True,
                ),
                "debtor_name": FieldConfig(
                    type=FieldType.STRING,
                    xpath="./deudor/denominacion/text()",
                    required=True,
                    pii=PIITag.NON_PERSONAL,
                ),
                "debtor_nif_cif": FieldConfig(
                    type=FieldType.STRING,
                    xpath="./deudor/nif_cif/text()",
                ),
                "proceeding_type_code": FieldConfig(
                    type=FieldType.STRING,
                    xpath="./tipo_procedimiento/text()",
                    required=True,
                ),
                "opened_at": FieldConfig(
                    type=FieldType.DATE,
                    xpath="./fecha_auto/text()",
                    required=True,
                    date_format="%Y-%m-%d",
                ),
                "administrator_name": FieldConfig(
                    type=FieldType.STRING,
                    xpath="./administrador_concursal/nombre/text()",
                    pii=PIITag.PERSONAL,
                ),
                "edicto_text": FieldConfig(
                    type=FieldType.STRING,
                    xpath="./texto/text()",
                ),
            },
            natural_key_fields=["edicto_id"],
        ),
    )

    def postprocess(self, fields: dict[str, Any]) -> dict[str, Any]:
        code = fields.get("proceeding_type_code")
        if isinstance(code, str) and code:
            label = BOE_TYPE_TO_LABEL.get(code.upper(), code)
            fields["proceeding_type_original"] = label
            fields["proceeding_type"] = map_proceeding_type(label).value

        fields["jurisdiction"] = "ES"

        if (pd := fields.get("publication_date")) and hasattr(pd, "isoformat"):
            fields["publication_date"] = pd.isoformat()

        return fields
