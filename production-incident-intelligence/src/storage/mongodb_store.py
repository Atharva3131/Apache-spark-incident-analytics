"""
MongoDB persistence layer.

Stores incident records, investigation history, and provides query interface.

If MongoDB is unavailable or disabled, operations fail gracefully and log warnings.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from config.settings import MongoConfig
from src.models.incident import IncidentRecord

logger = logging.getLogger(__name__)

# Lazy import – only when needed
_pymongo_available = False
try:
    from pymongo import MongoClient
    from pymongo.errors import ServerSelectionTimeoutError, OperationFailure

    _pymongo_available = True
except ImportError:
    logger.warning("pymongo not installed – MongoDB storage disabled")


class MongoDBStore:
    """
    Wrapper around MongoDB client.
    """

    def __init__(self, config: MongoConfig):
        self._config = config
        self._client = None
        self._db = None
        if config.enabled and _pymongo_available:
            self._connect()

    def _connect(self) -> bool:
        """Attempt to connect to MongoDB."""
        if not _pymongo_available:
            logger.warning("pymongo not available – skipping MongoDB connection")
            return False
        try:
            logger.info("Connecting to MongoDB: %s", self._config.uri)
            self._client = MongoClient(self._config.uri, serverSelectionTimeoutMS=5000)
            self._db = self._client[self._config.database]
            # Test connection
            self._db.command("ping")
            logger.info("Connected to MongoDB successfully")
            return True
        except ServerSelectionTimeoutError:
            logger.error("MongoDB connection timeout – storage will be unavailable")
            self._client = None
            self._db = None
            return False
        except Exception as e:
            logger.error("MongoDB connection failed: %s", e)
            self._client = None
            self._db = None
            return False

    def is_connected(self) -> bool:
        return self._db is not None

    def store_incident(self, incident: IncidentRecord) -> bool:
        """
        Store an incident record. Returns True if successful, False otherwise.
        """
        if not self.is_connected():
            logger.debug("MongoDB not connected – skipping incident storage")
            return False
        try:
            collection = self._db[self._config.collection_incidents]
            doc = incident.dict()
            result = collection.insert_one(doc)
            logger.info("Incident stored with ID: %s", result.inserted_id)
            return True
        except Exception as e:
            logger.error("Failed to store incident: %s", e)
            return False

    def get_incident(self, incident_id: str) -> Optional[IncidentRecord]:
        """Retrieve a single incident by ID."""
        if not self.is_connected():
            return None
        try:
            collection = self._db[self._config.collection_incidents]
            doc = collection.find_one({"incident_id": incident_id})
            if doc is None:
                return None
            # Remove MongoDB's _id field before passing to Pydantic
            doc.pop("_id", None)
            return IncidentRecord(**doc)
        except Exception as e:
            logger.error("Failed to retrieve incident: %s", e)
            return None

    def list_incidents(self, limit: int = 100, status: Optional[str] = None) -> List[IncidentRecord]:
        """List recent incidents, optionally filtered by status."""
        if not self.is_connected():
            return []
        try:
            collection = self._db[self._config.collection_incidents]
            query = {} if status is None else {"status": status}
            docs = list(
                collection.find(query)
                .sort("detected_at", -1)
                .limit(limit)
            )
            results = []
            for doc in docs:
                doc.pop("_id", None)
                results.append(IncidentRecord(**doc))
            logger.info("Retrieved %d incidents", len(results))
            return results
        except Exception as e:
            logger.error("Failed to list incidents: %s", e)
            return []

    def update_incident_status(self, incident_id: str, status: str) -> bool:
        """Update an incident's status (e.g., 'investigating' -> 'resolved')."""
        if not self.is_connected():
            return False
        try:
            collection = self._db[self._config.collection_incidents]
            result = collection.update_one(
                {"incident_id": incident_id},
                {"$set": {"status": status}},
            )
            if result.matched_count == 0:
                logger.warning("Incident %s not found", incident_id)
                return False
            logger.info("Updated incident %s status to %s", incident_id, status)
            return True
        except Exception as e:
            logger.error("Failed to update incident: %s", e)
            return False

    def delete_incident(self, incident_id: str) -> bool:
        """Delete an incident record."""
        if not self.is_connected():
            return False
        try:
            collection = self._db[self._config.collection_incidents]
            result = collection.delete_one({"incident_id": incident_id})
            if result.deleted_count == 0:
                logger.warning("Incident %s not found", incident_id)
                return False
            logger.info("Deleted incident %s", incident_id)
            return True
        except Exception as e:
            logger.error("Failed to delete incident: %s", e)
            return False

    def log_investigation_history(
        self,
        incident_id: str,
        model_used: str,
        investigation_result: Dict,
    ) -> bool:
        """
        Store investigation history for audit/analysis.
        """
        if not self.is_connected():
            return False
        try:
            collection = self._db[self._config.collection_history]
            doc = {
                "incident_id": incident_id,
                "model_used": model_used,
                "investigation_result": investigation_result,
                "timestamp": __import__("datetime").datetime.utcnow(),
            }
            result = collection.insert_one(doc)
            logger.info("Investigation history logged: %s", result.inserted_id)
            return True
        except Exception as e:
            logger.error("Failed to log investigation history: %s", e)
            return False

    def close(self):
        """Clean up MongoDB connection."""
        if self._client:
            self._client.close()
            logger.info("MongoDB connection closed")
