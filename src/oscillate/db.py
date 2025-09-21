import json
import sqlite3
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Optional, List
from datetime import datetime

import aiosqlite

from oscillate.exceptions import DBError
from oscillate.utils.logging import get_logger
from oscillate.utils.typing import DBResult

logger = get_logger(__name__)


class DBManager(ABC):
    """Abstract database manager interface."""
    
    @abstractmethod
    async def save_queue_state(self, guild_id: int, data: Dict[str, Any]) -> None:
        """Save queue state for a guild."""
        pass
    
    @abstractmethod
    async def load_queue_state(self, guild_id: int) -> Optional[Dict[str, Any]]:
        """Load queue state for a guild."""
        pass
    
    @abstractmethod
    async def clear_queue_state(self, guild_id: int) -> None:
        """Clear queue state for a guild."""
        pass
    
    @abstractmethod
    async def save_track_history(self, guild_id: int, track_data: Dict[str, Any]) -> None:
        """Save track to history."""
        pass
    
    @abstractmethod
    async def get_track_history(self, guild_id: int, limit: int = 50) -> DBResult:
        """Get track history for a guild."""
        pass
    
    @abstractmethod
    async def get_guild_stats(self, guild_id: int) -> Dict[str, Any]:
        """Get statistics for a guild."""
        pass
    
    @abstractmethod
    async def initialize(self) -> None:
        """Initialize database connection and schema."""
        pass
    
    @abstractmethod
    async def close(self) -> None:
        """Close database connection."""
        pass


class SQLiteDBManager(DBManager):
    """SQLite implementation of database manager."""
    
    def __init__(self, db_path: str = "oscillate.db"):
        """
        Initialize SQLite database manager.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self._db: Optional[aiosqlite.Connection] = None
        self._initialized = False
    
    async def initialize(self) -> None:
        """Initialize database connection and create tables."""
        if self._initialized:
            return
        
        try:
            # Ensure directory exists
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Connect to database
            self._db = await aiosqlite.connect(self.db_path)
            self._db.row_factory = aiosqlite.Row
            
            # Create tables
            await self._create_tables()
            await self._db.commit()
            
            self._initialized = True
            logger.info(f"SQLite database initialized: {self.db_path}")
            
        except Exception as e:
            raise DBError(f"Failed to initialize database: {e}")
    
    async def _create_tables(self) -> None:
        """Create database tables if they don't exist."""
        # Queue states table
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS queue_states (
                guild_id INTEGER PRIMARY KEY,
                state_data TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Track history table
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS track_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                track_data TEXT NOT NULL,
                played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                requester_id INTEGER,
                duration INTEGER
            )
        """)
        
        # Guild statistics table
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS guild_stats (
                guild_id INTEGER PRIMARY KEY,
                total_tracks_played INTEGER DEFAULT 0,
                total_playtime_seconds INTEGER DEFAULT 0,
                last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                most_played_track TEXT,
                most_active_user INTEGER
            )
        """)
        
        # Indexes for better performance
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_track_history_guild 
            ON track_history(guild_id, played_at DESC)
        """)
        
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_track_history_requester 
            ON track_history(guild_id, requester_id)
        """)
    
    async def _ensure_initialized(self) -> None:
        """Ensure database is initialized before operations."""
        if not self._initialized:
            await self.initialize()
    
    async def save_queue_state(self, guild_id: int, data: Dict[str, Any]) -> None:
        """Save queue state for a guild."""
        await self._ensure_initialized()
        try:
            state_json = json.dumps(data, default=str)
            await self._db.execute("""
                INSERT OR REPLACE INTO queue_states (guild_id, state_data, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            """, (guild_id, state_json))
            await self._db.commit()
            logger.debug(f"Saved queue state for guild {guild_id}")
        except Exception as e:
            raise DBError(f"Failed to save queue state for guild {guild_id}: {e}")
    
    async def load_queue_state(self, guild_id: int) -> Optional[Dict[str, Any]]:
        """Load queue state for a guild."""
        await self._ensure_initialized()
        try:
            cursor = await self._db.execute("""
                SELECT state_data FROM queue_states WHERE guild_id = ?
            """, (guild_id,))
            row = await cursor.fetchone()
            if row:
                return json.loads(row['state_data'])
            return None
        except Exception as e:
            raise DBError(f"Failed to load queue state for guild {guild_id}: {e}")
    
    async def clear_queue_state(self, guild_id: int) -> None:
        """Clear queue state for a guild."""
        await self._ensure_initialized()
        try:
            await self._db.execute("DELETE FROM queue_states WHERE guild_id = ?", (guild_id,))
            await self._db.commit()
            logger.debug(f"Cleared queue state for guild {guild_id}")
        except Exception as e:
            raise DBError(f"Failed to clear queue state for guild {guild_id}: {e}")
    
    async def save_track_history(self, guild_id: int, track_data: Dict[str, Any]) -> None:
        """Save track to history."""
        await self._ensure_initialized()
        try:
            track_json = json.dumps(track_data, default=str)
            requester_id = track_data.get("requester_id")
            duration = track_data.get("duration")
            await self._db.execute("""
                INSERT INTO track_history (guild_id, track_data, requester_id, duration)
                VALUES (?, ?, ?, ?)
            """, (guild_id, track_json, requester_id, duration))
            await self._update_guild_stats(guild_id, track_data)
            await self._db.commit()
            logger.debug(f"Saved track history for guild {guild_id}")
        except Exception as e:
            raise DBError(f"Failed to save track history for guild {guild_id}: {e}")
    
    async def get_track_history(self, guild_id: int, limit: int = 50) -> DBResult:
        """Get track history for a guild."""
        await self._ensure_initialized()
        try:
            cursor = await self._db.execute("""
                SELECT track_data, played_at, requester_id, duration
                FROM track_history 
                WHERE guild_id = ? 
                ORDER BY played_at DESC 
                LIMIT ?
            """, (guild_id, limit))
            rows = await cursor.fetchall()
            result = []
            for row in rows:
                track_data = json.loads(row['track_data'])
                result.append({
                    "track": track_data,
                    "played_at": row['played_at'],
                    "requester_id": row['requester_id'],
                    "duration": row['duration'],
                })
            return result
        except Exception as e:
            raise DBError(f"Failed to get track history for guild {guild_id}: {e}")
    
    async def get_guild_stats(self, guild_id: int) -> Dict[str, Any]:
        """Get statistics for a guild."""
        await self._ensure_initialized()
        try:
            cursor = await self._db.execute("SELECT * FROM guild_stats WHERE guild_id = ?", (guild_id,))
            stats_row = await cursor.fetchone()
            if not stats_row:
                return {
                    "guild_id": guild_id,
                    "total_tracks_played": 0,
                    "total_playtime_seconds": 0,
                    "last_activity": None,
                    "most_played_track": None,
                    "most_active_user": None,
                }
            # Most played track
            cursor = await self._db.execute("""
                SELECT track_data, COUNT(*) as play_count
                FROM track_history 
                WHERE guild_id = ? 
                GROUP BY JSON_EXTRACT(track_data, '$.audio_url')
                ORDER BY play_count DESC 
                LIMIT 1
            """, (guild_id,))
            most_played_row = await cursor.fetchone()
            most_played_track = None
            if most_played_row:
                most_played_track = {
                    "track": json.loads(most_played_row['track_data']),
                    "play_count": most_played_row['play_count'],
                }
            # Most active user
            cursor = await self._db.execute("""
                SELECT requester_id, COUNT(*) as request_count
                FROM track_history 
                WHERE guild_id = ? AND requester_id IS NOT NULL
                GROUP BY requester_id 
                ORDER BY request_count DESC 
                LIMIT 1
            """, (guild_id,))
            most_active_row = await cursor.fetchone()
            most_active_user = None
            if most_active_row:
                most_active_user = {
                    "user_id": most_active_row['requester_id'],
                    "request_count": most_active_row['request_count'],
                }
            return {
                "guild_id": guild_id,
                "total_tracks_played": stats_row['total_tracks_played'],
                "total_playtime_seconds": stats_row['total_playtime_seconds'],
                "last_activity": stats_row['last_activity'],
                "most_played_track": most_played_track,
                "most_active_user": most_active_user,
            }
        except Exception as e:
            raise DBError(f"Failed to get guild stats for guild {guild_id}: {e}")
    
    async def _update_guild_stats(self, guild_id: int, track_data: Dict[str, Any]) -> None:
        """Update guild statistics after track play."""
        duration = track_data.get("duration", 0) or 0
        await self._db.execute("""
            INSERT OR REPLACE INTO guild_stats (
                guild_id, total_tracks_played, total_playtime_seconds, last_activity
            ) VALUES (
                ?,
                COALESCE((SELECT total_tracks_played FROM guild_stats WHERE guild_id = ?), 0) + 1,
                COALESCE((SELECT total_playtime_seconds FROM guild_stats WHERE guild_id = ?), 0) + ?,
                CURRENT_TIMESTAMP
            )
        """, (guild_id, guild_id, guild_id, duration))
    
    async def cleanup_old_history(self, days: int = 30) -> int:
        """Clean up old track history records."""
        await self._ensure_initialized()
        try:
            cursor = await self._db.execute(f"""
                DELETE FROM track_history 
                WHERE played_at < datetime('now', '-{days} days')
            """)
            await self._db.commit()
            deleted_count = cursor.rowcount
            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} old track history records")
            return deleted_count
        except Exception as e:
            raise DBError(f"Failed to cleanup old history: {e}")
    
    async def export_guild_data(self, guild_id: int) -> Dict[str, Any]:
        """Export all data for a guild."""
        await self._ensure_initialized()
        try:
            queue_state = await self.load_queue_state(guild_id)
            cursor = await self._db.execute("""
                SELECT track_data, played_at, requester_id, duration
                FROM track_history 
                WHERE guild_id = ? 
                ORDER BY played_at DESC
            """, (guild_id,))
            history_rows = await cursor.fetchall()
            history = []
            for row in history_rows:
                history.append({
                    "track": json.loads(row['track_data']),
                    "played_at": row['played_at'],
                    "requester_id": row['requester_id'],
                    "duration": row['duration'],
                })
            stats = await self.get_guild_stats(guild_id)
            return {
                "guild_id": guild_id,
                "export_timestamp": datetime.utcnow().isoformat(),  # fixed
                "queue_state": queue_state,
                "track_history": history,
                "statistics": stats,
            }
        except Exception as e:
            raise DBError(f"Failed to export data for guild {guild_id}: {e}")
    
    async def import_guild_data(self, data: Dict[str, Any]) -> None:
        """Import guild data from export."""
        await self._ensure_initialized()
        try:
            guild_id = data["guild_id"]
            if data.get("queue_state"):
                await self.save_queue_state(guild_id, data["queue_state"])
            for history_item in data.get("track_history", []):
                track_data = history_item["track"]
                await self._db.execute("""
                    INSERT INTO track_history (guild_id, track_data, played_at, requester_id, duration)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    guild_id,
                    json.dumps(track_data),
                    history_item.get("played_at"),
                    history_item.get("requester_id"),
                    history_item.get("duration"),
                ))
            await self._db.commit()
            logger.info(f"Imported data for guild {guild_id}")
        except Exception as e:
            raise DBError(f"Failed to import guild data: {e}")
    
    async def close(self) -> None:
        """Close database connection."""
        if self._db:
            await self._db.close()
            self._db = None
            self._initialized = False
            logger.info("SQLite database connection closed")
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()


class RedisDBManager(DBManager):
    """Redis implementation of database manager (stub for future implementation)."""
    
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        """Initialize Redis database manager."""
        self.redis_url = redis_url
        self._redis = None
        raise NotImplementedError("Redis implementation coming soon")
    
    async def save_queue_state(self, guild_id: int, data: Dict[str, Any]) -> None: raise NotImplementedError()
    async def load_queue_state(self, guild_id: int) -> Optional[Dict[str, Any]]: raise NotImplementedError()
    async def clear_queue_state(self, guild_id: int) -> None: raise NotImplementedError()
    async def save_track_history(self, guild_id: int, track_data: Dict[str, Any]) -> None: raise NotImplementedError()
    async def get_track_history(self, guild_id: int, limit: int = 50) -> DBResult: raise NotImplementedError()
    async def get_guild_stats(self, guild_id: int) -> Dict[str, Any]: raise NotImplementedError()
    async def initialize(self) -> None: raise NotImplementedError()
    async def close(self) -> None: raise NotImplementedError()


class MemoryDBManager(DBManager):
    """In-memory database manager for testing and development."""
    
    def __init__(self):
        """Initialize memory database manager."""
        self._queue_states: Dict[int, Dict[str, Any]] = {}
        self._track_history: Dict[int, List[Dict[str, Any]]] = {}
        self._guild_stats: Dict[int, Dict[str, Any]] = {}
        self._initialized = False
    
    async def initialize(self) -> None:
        """Initialize memory storage."""
        self._initialized = True
        logger.info("Memory database manager initialized")
    
    async def save_queue_state(self, guild_id: int, data: Dict[str, Any]) -> None:
        """Save queue state in memory."""
        self._queue_states[guild_id] = data.copy()
    
    async def load_queue_state(self, guild_id: int) -> Optional[Dict[str, Any]]:
        """Load queue state from memory."""
        return self._queue_states.get(guild_id)
    
    async def clear_queue_state(self, guild_id: int) -> None:
        """Clear queue state from memory."""
        self._queue_states.pop(guild_id, None)
    
    async def save_track_history(self, guild_id: int, track_data: Dict[str, Any]) -> None:
        """Save track history in memory."""
        if guild_id not in self._track_history:
            self._track_history[guild_id] = []
        self._track_history[guild_id].append({
            "track": track_data,
            "played_at": datetime.utcnow().isoformat(),  # fixed datetime
            "requester_id": track_data.get("requester_id"),
            "duration": track_data.get("duration"),
        })
        if len(self._track_history[guild_id]) > 1000:
            self._track_history[guild_id] = self._track_history[guild_id][-1000:]
    
    async def get_track_history(self, guild_id: int, limit: int = 50) -> DBResult:
        """Get track history from memory."""
        history = self._track_history.get(guild_id, [])
        return history[-limit:][::-1]
    
    async def get_guild_stats(self, guild_id: int) -> Dict[str, Any]:
        """Get guild stats from memory."""
        return self._guild_stats.get(guild_id, {
            "guild_id": guild_id,
            "total_tracks_played": 0,
            "total_playtime_seconds": 0,
            "last_activity": None,
            "most_played_track": None,
            "most_active_user": None,
        })
    
    async def close(self) -> None:
        """Clear memory storage."""
        self._queue_states.clear()
        self._track_history.clear()
        self._guild_stats.clear()
        self._initialized = False
        logger.info("Memory database manager cleared")
