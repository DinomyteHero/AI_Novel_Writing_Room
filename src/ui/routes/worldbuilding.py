"""Worldbuilding API endpoints — universes, lore entries, relations, import."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from src.ui.app import get_app_state

router = APIRouter(prefix="/worldbuilding", tags=["worldbuilding"])


def _require_lore_service(request: Request):
    state = get_app_state(request)
    if not state.lore_service:
        raise HTTPException(503, "Worldbuilding service not initialized")
    return state


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class UniverseCreate(BaseModel):
    universe_id: str
    display_name: str
    parent_universe_id: Optional[str] = None
    franchise: Optional[str] = None
    description: Optional[str] = None
    embedding_model: Optional[str] = None


class LoreEntryCreate(BaseModel):
    category: str
    title: str
    content: str
    status: str = "canonical"
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    thematic_notes: Optional[str] = None
    speech_patterns: Optional[str] = None
    canon_override: bool = False
    override_notes: Optional[str] = None
    tags: Optional[list[str]] = None
    source_project_id: Optional[str] = None
    introduced_in_project_id: Optional[str] = None
    extraction_source: str = "author"


class LoreEntryUpdate(BaseModel):
    category: Optional[str] = None
    title: Optional[str] = None
    content: Optional[str] = None
    status: Optional[str] = None
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    thematic_notes: Optional[str] = None
    speech_patterns: Optional[str] = None
    canon_override: Optional[bool] = None
    override_notes: Optional[str] = None
    tags: Optional[list[str]] = None


class RelationCreate(BaseModel):
    source_entry_id: str
    target_entry_id: str
    relation_type: str
    description: Optional[str] = None
    dialogue_implications: Optional[str] = None


class ProjectBindCreate(BaseModel):
    universe_id: str
    reading_order: int = 0
    timeline_start: Optional[str] = None
    timeline_end: Optional[str] = None


class BulkPromote(BaseModel):
    entry_ids: list[str]


class AffiliationCreate(BaseModel):
    character_id: str
    entry_id: str
    affiliation_type: str = "member"


class ImportSeedRequest(BaseModel):
    concept_seed: dict


class ExtractChapterRequest(BaseModel):
    chapter_text: str
    scene_card: dict = {}
    project_id: str = ""


# ------------------------------------------------------------------
# Universe endpoints
# ------------------------------------------------------------------

@router.post("/universes", status_code=201)
async def create_universe(body: UniverseCreate, request: Request):
    state = _require_lore_service(request)
    try:
        state.lore_service.create_universe(
            universe_id=body.universe_id,
            display_name=body.display_name,
            parent_universe_id=body.parent_universe_id,
            franchise=body.franchise,
            description=body.description,
            embedding_model=body.embedding_model,
        )
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"universe_id": body.universe_id, "status": "created"}


@router.get("/universes")
async def list_universes(request: Request):
    state = _require_lore_service(request)
    return {"universes": state.lore_service.db.list_universes()}


@router.get("/universes/{universe_id}")
async def get_universe(universe_id: str, request: Request):
    state = _require_lore_service(request)
    universe = state.lore_service.db.get_universe(universe_id)
    if not universe:
        raise HTTPException(404, f"Universe not found: {universe_id}")
    chain = state.lore_service.db.get_universe_chain(universe_id)
    return {**universe, "inheritance_chain": chain}


@router.delete("/universes/{universe_id}")
async def delete_universe(universe_id: str, request: Request):
    state = _require_lore_service(request)
    universe = state.lore_service.db.get_universe(universe_id)
    if not universe:
        raise HTTPException(404, f"Universe not found: {universe_id}")
    state.lore_service.delete_universe(universe_id)
    return {"status": "deleted"}


# ------------------------------------------------------------------
# Lore entry endpoints
# ------------------------------------------------------------------

@router.get("/universes/{universe_id}/lore")
async def list_lore_entries(
    universe_id: str,
    request: Request,
    category: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
):
    state = _require_lore_service(request)
    entries = state.lore_service.db.list_lore_entries(
        universe_id, category=category, status=status, text_search=search,
    )
    return {"entries": entries, "count": len(entries)}


@router.post("/universes/{universe_id}/lore", status_code=201)
async def create_lore_entry(
    universe_id: str,
    body: LoreEntryCreate,
    request: Request,
):
    state = _require_lore_service(request)
    universe = state.lore_service.db.get_universe(universe_id)
    if not universe:
        raise HTTPException(404, f"Universe not found: {universe_id}")
    try:
        entry_id = state.lore_service.create_lore_entry(
            universe_id=universe_id,
            category=body.category,
            title=body.title,
            content=body.content,
            status=body.status,
            valid_from=body.valid_from,
            valid_until=body.valid_until,
            thematic_notes=body.thematic_notes,
            speech_patterns=body.speech_patterns,
            canon_override=body.canon_override,
            override_notes=body.override_notes,
            tags=body.tags,
            source_project_id=body.source_project_id,
            introduced_in_project_id=body.introduced_in_project_id,
            extraction_source=body.extraction_source,
        )
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"entry_id": entry_id, "status": "created"}


@router.get("/lore/{entry_id}")
async def get_lore_entry(entry_id: str, request: Request):
    state = _require_lore_service(request)
    entry = state.lore_service.db.get_lore_entry(entry_id)
    if not entry:
        raise HTTPException(404, f"Lore entry not found: {entry_id}")
    relations = state.lore_service.db.get_relations(entry_id)
    return {**entry, "relations": relations}


@router.put("/lore/{entry_id}")
async def update_lore_entry(
    entry_id: str,
    body: LoreEntryUpdate,
    request: Request,
):
    state = _require_lore_service(request)
    entry = state.lore_service.db.get_lore_entry(entry_id)
    if not entry:
        raise HTTPException(404, f"Lore entry not found: {entry_id}")
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if fields:
        try:
            state.lore_service.update_lore_entry(entry_id, **fields)
        except Exception as e:
            raise HTTPException(400, str(e))
    return {"entry_id": entry_id, "status": "updated"}


@router.delete("/lore/{entry_id}")
async def delete_lore_entry(entry_id: str, request: Request):
    state = _require_lore_service(request)
    state.lore_service.delete_lore_entry(entry_id)
    return {"status": "deleted"}


@router.post("/lore/{entry_id}/promote")
async def promote_lore_entry(entry_id: str, request: Request):
    state = _require_lore_service(request)
    entry = state.lore_service.db.get_lore_entry(entry_id)
    if not entry:
        raise HTTPException(404, f"Lore entry not found: {entry_id}")
    state.lore_service.promote_entry(entry_id)
    return {"entry_id": entry_id, "status": "canonical"}


@router.post("/lore/{entry_id}/deprecate")
async def deprecate_lore_entry(entry_id: str, request: Request):
    state = _require_lore_service(request)
    entry = state.lore_service.db.get_lore_entry(entry_id)
    if not entry:
        raise HTTPException(404, f"Lore entry not found: {entry_id}")
    state.lore_service.deprecate_entry(entry_id)
    return {"entry_id": entry_id, "status": "deprecated"}


@router.post("/lore/bulk-promote")
async def bulk_promote(body: BulkPromote, request: Request):
    state = _require_lore_service(request)
    promoted = []
    for eid in body.entry_ids:
        entry = state.lore_service.db.get_lore_entry(eid)
        if entry:
            state.lore_service.promote_entry(eid)
            promoted.append(eid)
    return {"promoted": promoted, "count": len(promoted)}


# ------------------------------------------------------------------
# Relation endpoints
# ------------------------------------------------------------------

@router.post("/lore/relations", status_code=201)
async def create_relation(body: RelationCreate, request: Request):
    state = _require_lore_service(request)
    try:
        state.lore_service.link_entries(
            source_id=body.source_entry_id,
            target_id=body.target_entry_id,
            relation_type=body.relation_type,
            description=body.description,
            dialogue_implications=body.dialogue_implications,
        )
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"status": "created"}


@router.get("/lore/{entry_id}/relations")
async def get_relations(entry_id: str, request: Request):
    state = _require_lore_service(request)
    return {"relations": state.lore_service.db.get_relations(entry_id)}


@router.delete("/lore/relations/{source_id}/{target_id}/{relation_type}")
async def delete_relation(
    source_id: str,
    target_id: str,
    relation_type: str,
    request: Request,
):
    state = _require_lore_service(request)
    state.lore_service.db.delete_relation(source_id, target_id, relation_type)
    return {"status": "deleted"}


# ------------------------------------------------------------------
# Terminology
# ------------------------------------------------------------------

@router.get("/universes/{universe_id}/terminology")
async def get_terminology(universe_id: str, request: Request):
    state = _require_lore_service(request)
    terms = state.lore_service.get_terminology(universe_id)
    return {"terminology": terms, "count": len(terms)}


# ------------------------------------------------------------------
# Project binding
# ------------------------------------------------------------------

@router.post("/projects/{project_id}/bind-universe", status_code=201)
async def bind_project(
    project_id: str,
    body: ProjectBindCreate,
    request: Request,
):
    state = _require_lore_service(request)
    universe = state.lore_service.db.get_universe(body.universe_id)
    if not universe:
        raise HTTPException(404, f"Universe not found: {body.universe_id}")
    state.lore_service.db.bind_project(
        project_id=project_id,
        universe_id=body.universe_id,
        reading_order=body.reading_order,
        timeline_start=body.timeline_start,
        timeline_end=body.timeline_end,
    )
    return {"project_id": project_id, "universe_id": body.universe_id}


@router.get("/projects/{project_id}/universe")
async def get_project_universe(project_id: str, request: Request):
    state = _require_lore_service(request)
    binding = state.lore_service.db.get_project_binding(project_id)
    if not binding:
        raise HTTPException(404, f"No universe bound to project: {project_id}")
    universe = state.lore_service.db.get_universe(binding["universe_id"])
    return {"binding": binding, "universe": universe}


# ------------------------------------------------------------------
# Import & extraction
# ------------------------------------------------------------------

@router.post("/universes/{universe_id}/import-seed")
async def import_from_seed(
    universe_id: str,
    body: ImportSeedRequest,
    request: Request,
):
    state = _require_lore_service(request)
    universe = state.lore_service.db.get_universe(universe_id)
    if not universe:
        raise HTTPException(404, f"Universe not found: {universe_id}")
    if not state.router:
        raise HTTPException(503, "Model router not initialized")

    entry_ids = await state.lore_service.import_from_concept_seed(
        concept_seed=body.concept_seed,
        universe_id=universe_id,
        router=state.router,
    )
    return {"entry_ids": entry_ids, "count": len(entry_ids)}


@router.post("/universes/{universe_id}/extract-chapter")
async def extract_from_chapter(
    universe_id: str,
    body: ExtractChapterRequest,
    request: Request,
):
    state = _require_lore_service(request)
    universe = state.lore_service.db.get_universe(universe_id)
    if not universe:
        raise HTTPException(404, f"Universe not found: {universe_id}")
    if not state.router:
        raise HTTPException(503, "Model router not initialized")

    entry_ids = await state.lore_service.extract_worldbuilding_from_chapter(
        chapter_text=body.chapter_text,
        scene_card=body.scene_card,
        universe_id=universe_id,
        project_id=body.project_id,
        router=state.router,
    )
    return {"entry_ids": entry_ids, "count": len(entry_ids)}


@router.get("/universes/{universe_id}/pending")
async def list_pending_entries(universe_id: str, request: Request):
    state = _require_lore_service(request)
    entries = state.lore_service.db.list_lore_entries(
        universe_id, status="provisional",
    )
    return {"entries": entries, "count": len(entries)}


# ------------------------------------------------------------------
# Maintenance
# ------------------------------------------------------------------

# ------------------------------------------------------------------
# Character affiliations
# ------------------------------------------------------------------

@router.post("/lore/affiliations", status_code=201)
async def create_affiliation(body: AffiliationCreate, request: Request):
    state = _require_lore_service(request)
    try:
        state.lore_service.db.affiliate_character(
            body.character_id, body.entry_id, body.affiliation_type,
        )
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"status": "created"}


@router.get("/lore/affiliations/{character_id}")
async def get_character_affiliations(character_id: str, request: Request):
    state = _require_lore_service(request)
    affiliations = state.lore_service.db.get_character_affiliations(character_id)
    return {"affiliations": affiliations}


@router.delete("/lore/affiliations/{character_id}/{entry_id}")
async def remove_affiliation(
    character_id: str, entry_id: str, request: Request,
):
    state = _require_lore_service(request)
    state.lore_service.db.remove_character_affiliation(character_id, entry_id)
    return {"status": "deleted"}


# ------------------------------------------------------------------
# Maintenance
# ------------------------------------------------------------------

@router.post("/admin/reconcile")
async def reconcile_chromadb(
    request: Request,
    universe_id: Optional[str] = Query(None),
):
    state = _require_lore_service(request)
    fixes = state.lore_service.reconcile_chromadb_orphans(universe_id)
    return {"fixes": fixes}
