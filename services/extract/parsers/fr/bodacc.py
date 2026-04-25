"""Parser for BODACC (Bulletin Officiel des Annonces Civiles et Commerciales).

BODACC publishes daily XML files. Each file contains many ``<annonce>``
elements, one per legal notice. We care about Section B (procédures
collectives) — the commerce-court insolvency/reorganization notices.

Reference: the public schema from DILA (Direction de l'information
légale et administrative). Field names below match the real XSD as of
2026-04; the canary fixture documents the exact structure expected.

Unlike the HTML parsers, this is a bulk parser — one payload, many
records. The `DeclarativeXmlBulkParser` handles that shape.
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


# Map BODACC's ``procedureCollective`` type codes to the local label
# the unified taxonomy mapper knows about. The raw code is preserved on
# the record under proceeding_type_original_code for audit.
BODACC_TYPE_TO_LABEL: dict[str, str] = {
    "LJ": "Liquidation judiciaire",
    "RJ": "Redressement judiciaire",
    "SV": "Procédure de sauvegarde",
    "SA": "Sauvegarde accélérée",
    "CON": "Conciliation",
    "MAH": "Mandat ad hoc",
}


class BodaccParser(DeclarativeXmlBulkParser):
    """BODACC-B annonce parser.

    The canonical xpath is ``/BODACC_B/annonce`` — that's the v2
    schema. Some historical files use ``/bodacc/annonce`` (lowercase);
    parsers for older archives should subclass and override if needed.
    """

    PARSER_ID = "parsers.fr.bodacc_v1"
    VERSION = "1.0.0"
    records_xpath = "/BODACC_B/annonce"

    config = ExtractionConfig(
        content_type="xml",
        record=RecordPath(
            fields={
                # BODACC assigns a stable numeroAnnonce unique within a daily
                # file — perfect natural key when combined with the publication date.
                "annonce_number": FieldConfig(
                    type=FieldType.STRING,
                    xpath="./numeroAnnonce/text()",
                    required=True,
                ),
                "publication_date": FieldConfig(
                    type=FieldType.DATE,
                    xpath="./dateParution/text()",
                    required=True,
                    date_format="%Y-%m-%d",
                ),
                "tribunal_name": FieldConfig(
                    type=FieldType.STRING,
                    xpath="./tribunal/text()",
                    required=True,
                ),
                "debtor_name": FieldConfig(
                    type=FieldType.STRING,
                    xpath="./personne/denomination/text()",
                    required=True,
                    pii=PIITag.NON_PERSONAL,
                ),
                "debtor_legal_form": FieldConfig(
                    type=FieldType.STRING,
                    xpath="./personne/formeJuridique/text()",
                ),
                "debtor_siren": FieldConfig(
                    type=FieldType.STRING,
                    xpath="./personne/numeroImmatriculation/siren/text()",
                    regex=r"(\d{9})",
                ),
                "debtor_rcs": FieldConfig(
                    type=FieldType.STRING,
                    xpath="./personne/numeroImmatriculation/rcs/text()",
                ),
                "debtor_naf": FieldConfig(
                    type=FieldType.STRING,
                    xpath="./personne/codeAPE/text()",
                ),
                "proceeding_type_code": FieldConfig(
                    type=FieldType.STRING,
                    xpath="./procedureCollective/typeProcedure/text()",
                    required=True,
                ),
                "opened_at": FieldConfig(
                    type=FieldType.DATE,
                    xpath="./procedureCollective/dateJugement/text()",
                    required=True,
                    date_format="%Y-%m-%d",
                ),
                "administrator_name": FieldConfig(
                    type=FieldType.STRING,
                    xpath="./mandataire/nom/text()",
                    pii=PIITag.PERSONAL,
                ),
                "administrator_role": FieldConfig(
                    type=FieldType.STRING,
                    xpath="./mandataire/qualite/text()",
                ),
            },
            natural_key_fields=["annonce_number", "publication_date"],
        ),
    )

    def postprocess(self, fields: dict[str, Any]) -> dict[str, Any]:
        """Resolve BODACC type code → local label → unified taxonomy."""
        code = fields.get("proceeding_type_code")
        if isinstance(code, str) and code:
            label = BODACC_TYPE_TO_LABEL.get(code.upper(), code)
            fields["proceeding_type_original"] = label
            fields["proceeding_type"] = map_proceeding_type(label).value

        fields["jurisdiction"] = "FR"
        # Natural key needs to be stringifiable — dates → isoformat.
        if (pd := fields.get("publication_date")) and hasattr(pd, "isoformat"):
            fields["publication_date"] = pd.isoformat()
        if (o := fields.get("opened_at")) and hasattr(o, "isoformat"):
            fields["opened_at_iso"] = o.isoformat()

        return fields
