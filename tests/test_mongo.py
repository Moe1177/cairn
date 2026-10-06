"""0.6 Task 2: MongoDB collections from Mongoose models and driver calls link shared data."""

from pathlib import Path

import pytest

from cairn.detectors.database import DatabaseDetector, mongoose_collection
from cairn.model.graph import EdgeType, FactKind
from cairn.scan import scan_workspace
from tests.helpers import ctx_for, make_repo

MODEL = """import mongoose from "mongoose";
const QrCodeMapping =
  mongoose.models.QrCodeMapping ||
  mongoose.model("QrCodeMapping", qrCodeMappingSchema);
export default QrCodeMapping;
"""
SCRIPT = """import { MongoClient } from "mongodb";
const qr = db.collection('qrcodemappings')
"""
FIRESTORE = """import firebase from "firebase/app";
const users = db.collection("qrcodemappings");
"""


@pytest.mark.parametrize(
    ("model", "collection"),
    [
        ("User", "users"),
        ("CheckIn", "checkins"),
        ("Applications", "applications"),
        ("Settings", "settings"),
        ("Verified_Email", "verified_emails"),
        ("Category", "categories"),
        ("Person", "people"),
        ("Info", "info"),
    ],
)
def test_mongoose_names_collections_like_mongoose(model: str, collection: str) -> None:
    assert mongoose_collection(model) == collection


def test_models_and_driver_calls_become_collections(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path,
        "admin",
        {
            "models/qr.ts": MODEL,
            "models/meal.ts": 'import { model } from "mongoose";\nexport const Meal = model<IMeal>("Meal", mealSchema, "meal_log");\n',
            "scripts/seed.ts": SCRIPT,
        },
    )
    result = DatabaseDetector().run(ctx_for(tmp_path, repo))
    exposed = {f.value for f in result.exposes if f.kind is FactKind.DB_TABLE}
    consumed = {f.value for f in result.consumes if f.kind is FactKind.DB_TABLE}
    assert {"qrcodemappings", "meal_log"} <= exposed
    assert "qrcodemappings" in consumed


def test_apps_on_a_distinctive_collection_share_a_database(tmp_path: Path) -> None:
    make_repo(tmp_path, "admin", {"models/qr.ts": MODEL})
    make_repo(tmp_path, "event-checkin", {"scripts/qr.ts": SCRIPT})
    edges = scan_workspace(tmp_path).workspace.edges
    shared = [e for e in edges if e.type is EdgeType.SHARES_DB]
    assert [{e.source, e.target} for e in shared] == [{"admin", "event-checkin"}]


def test_firestore_collections_are_not_mongo(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, "web", {"src/db.ts": FIRESTORE})
    result = DatabaseDetector().run(ctx_for(tmp_path, repo))
    assert not [f for f in result.consumes if f.kind is FactKind.DB_TABLE]
