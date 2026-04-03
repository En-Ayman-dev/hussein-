import logging
from typing import Any, Dict, List

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, OWL, RDF, RDFS, SKOS

logger = logging.getLogger(__name__)
HESIN = Namespace("http://hesin.org/ontology#")

# Mappings for common vocabulary names used in concept fields
CONCEPT_TEXT_PREDICATES = [
    RDFS.label,
    SKOS.prefLabel,
    SKOS.altLabel,
    DCTERMS.title,
    RDFS.comment,
    DCTERMS.description,
]

DEFINITION_PREDICATES = [
    HESIN.definition,
    HESIN.description,
    SKOS.definition,
    RDFS.comment,
    DCTERMS.description,
]

QUOTE_PREDICATES = [
    HESIN.foundational_quote,
    URIRef("http://www.w3.org/2000/01/rdf-schema#comment"),
]

ACTIONS_PREDICATES = [
    HESIN.actions,
]

IMPORTANCE_PREDICATES = [
    HESIN.importance,
]

SYNONYM_PREDICATES = [
    HESIN.hasSynonym,
    SKOS.altLabel,
    SKOS.hiddenLabel,
    OWL.sameAs,
    URIRef("http://www.w3.org/2004/02/skos/core#altLabel"),
]

RELATION_PREDICATES = {
    "causes": HESIN.causes,
    "opposes": HESIN.opposes,
    "establishes": HESIN.establishes,
    "isMeansFor": HESIN.isMeansFor,
    "relatedTo": HESIN.relatedTo,
    "negates": HESIN.negates,
    "isConditionFor": HESIN.isConditionFor,
    "isCausedBy": HESIN.isCausedBy,
    "precedes": HESIN.precedes,
    "belongsToGroup": HESIN.belongsToGroup,
    "belongsToLesson": HESIN.belongsToLesson,
    "belongsToCollection": HESIN.belongsToCollection,
}


def _is_rdf_star(node: Any) -> bool:
    # RDF-star not supported in rdflib 7.x, always return False
    return False


def _literal_to_text(value: Any) -> str:
    if isinstance(value, Literal):
        return str(value)
    if isinstance(value, URIRef):
        return str(value)
    return str(value)


def _collect_values(graph: Graph, subject: URIRef, predicates: List[URIRef]) -> List[str]:
    results: List[str] = []
    for p in predicates:
        for o in graph.objects(subject=subject, predicate=p):
            if _is_rdf_star(o):
                continue
            # only accept plain literals, typed literals, or URIs
            results.append(_literal_to_text(o))
    return results


def _unique(seq: List[Any]) -> List[Any]:
    seen = set()
    out = []
    for item in seq:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _sanitize_ttl_data(ttl_text: str) -> str:
    """Strip RDF-star inline reified triples so rdflib turtle parser can handle older formats."""
    lines = ttl_text.splitlines()
    sanitized = []
    for line in lines:
        # remove explicit RDF-star comments/annotations like << ... >> rdfs:comment ...
        if "<<" in line and ">>" in line:
            continue
        sanitized.append(line)
    return "\n".join(sanitized)


def parse_ttl(file_path: str) -> Dict[str, Any]:
    """Parse TTL file and return structured dict.

    Returns:
        dict with keys: concepts, synonyms, relations, parse_errors (optional)
    """
    graph = Graph()
    result: Dict[str, Any] = {
        "concepts": [],
        "synonyms": [],
        "relations": [],
        "warnings": [],
    }

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            raw_data = f.read()

        # Strip unknown BOM characters to avoid rdf parser syntax errors.
        raw_data = raw_data.lstrip('\ufeff')

        sanitized_data = _sanitize_ttl_data(raw_data)
        graph.parse(data=sanitized_data, format="turtle")
    except Exception as exc:
        logger.exception("Failed to parse TTL")
        # Return context with parse error so API can report.
        return {
            "concepts": [],
            "synonyms": [],
            "relations": [],
            "parse_error": str(exc),
        }

    # Collect candidate concept resources (URIRefs only)
    concept_uris = {s for s, p, o in graph if isinstance(s, URIRef) and not _is_rdf_star(s)}

    for uri in sorted(concept_uris, key=lambda x: str(x)):
        if _is_rdf_star(uri):
            continue

        labels = _collect_values(graph, uri, [RDFS.label, SKOS.prefLabel, DCTERMS.title])
        definition = _collect_values(graph, uri, DEFINITION_PREDICATES)
        quote = _collect_values(graph, uri, QUOTE_PREDICATES)
        actions = _collect_values(graph, uri, ACTIONS_PREDICATES)
        importance = _collect_values(graph, uri, IMPORTANCE_PREDICATES)

        if not labels and not definition and not quote and not actions and not importance:
            # Nothing meaningful extracted; skip this URI as a concept unless it serves in relations/synonyms
            continue

        concept = {
            "uri": str(uri),
            "labels": _unique(labels),
            "definition": _unique(definition),
            "quote": _unique(quote),
            "actions": _unique(actions),
            "importance": _unique(importance),
        }

        result["concepts"].append(concept)

    # Extract synonyms across graph
    for s, p, o in graph:
        if _is_rdf_star(s) or _is_rdf_star(p) or _is_rdf_star(o):
            result["warnings"].append("Ignored RDF-star triple in synonym extraction")
            continue

        if p in SYNONYM_PREDICATES and isinstance(o, (Literal, URIRef)):
            result["synonyms"].append({
                "subject": str(s),
                "predicate": str(p),
                "object": _literal_to_text(o),
            })

    # Extract relation edges
    for s, p, o in graph:
        if _is_rdf_star(s) or _is_rdf_star(p) or _is_rdf_star(o):
            result["warnings"].append("Ignored RDF-star triple in relation extraction")
            continue

        for relation_name, relation_predicate in RELATION_PREDICATES.items():
            if p == relation_predicate and isinstance(s, URIRef) and isinstance(o, URIRef):
                result["relations"].append({
                    "type": relation_name,
                    "source": str(s),
                    "target": str(o),
                })
                break

    # dedupe synonyms and relations
    result["synonyms"] = sorted(
        {tuple(sorted(item.items())): item for item in result["synonyms"]}.values(),
        key=lambda x: (x["subject"], x["predicate"], x["object"])
    )

    result["relations"] = sorted(
        {tuple(sorted(item.items())): item for item in result["relations"]}.values(),
        key=lambda x: (x["type"], x["source"], x["target"])
    )

    return result


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Parse TTL file into structured JSON-like dict")
    parser.add_argument("path", help="TTL file path")
    args = parser.parse_args()

    output = parse_ttl(args.path)
    print(json.dumps(output, indent=2, ensure_ascii=False))
