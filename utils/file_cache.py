"""
File-based JSON Cache - Persistent storage with unlimited capacity.
Replaces RAM-based LRU cache for better persistence across restarts.
"""

import os
import json
import hashlib
import logging
import threading
from typing import Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class FileBasedCache:
    """
    File-based JSON cache with persistent storage.
    
    Features:
    - Stores cache in JSON file (persists across restarts)
    - No item limit - unlimited caching
    - Thread-safe with locking
    - Automatic directory creation
    """
    
    def __init__(self, cache_dir: str = None):
        """
        Initialize file-based cache.
        
        Args:
            cache_dir: Directory to store cache files. Defaults to 'cache' in project root.
        """
        self.cache_dir = cache_dir or os.path.join(os.path.dirname(os.path.dirname(__file__)), 'cache')
        self.cache_file = os.path.join(self.cache_dir, 'product_cache.json')
        self._lock = threading.Lock()
        self._cache = {}  # In-memory copy for fast access
        self._ensure_cache_dir()
        self._load_cache()
    
    def _ensure_cache_dir(self):
        """Create cache directory if it doesn't exist."""
        Path(self.cache_dir).mkdir(parents=True, exist_ok=True)
    
    def _load_cache(self):
        """Load cache from file into memory."""
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    self._cache = json.load(f)
                logger.info(f"Loaded {len(self._cache)} items from cache file")
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to load cache file, starting fresh: {e}")
            self._cache = {}
    
    def _save_cache(self):
        """Save in-memory cache to file."""
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self._cache, f, ensure_ascii=False, indent=2)
        except IOError as e:
            logger.error(f"Failed to save cache file: {e}")
    
    def _hash_key(self, key: str) -> str:
        """Generate a safe hash key from the original key."""
        return hashlib.md5(key.encode('utf-8')).hexdigest()
    
    def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache.
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None if not found
        """
        hashed_key = self._hash_key(key)
        with self._lock:
            entry = self._cache.get(hashed_key)
            if entry:
                return entry.get('value')
        return None
    
    def set(self, key: str, value: Any):
        """
        Set value in cache.
        
        Args:
            key: Cache key
            value: Value to cache
        """
        hashed_key = self._hash_key(key)
        with self._lock:
            self._cache[hashed_key] = {
                'key_preview': key[:100] if len(key) > 100 else key,  # Store preview for debugging
                'value': value
            }
            self._save_cache()
    
    def clear(self):
        """Clear all cached items."""
        with self._lock:
            items_count = len(self._cache)
            self._cache = {}
            self._save_cache()
            logger.info(f"Cache cleared: {items_count} items removed")
            return items_count
    
    def count(self) -> int:
        """Get number of cached items."""
        with self._lock:
            return len(self._cache)
    
    @property
    def cache(self):
        """Property for backward compatibility with LRUCache.cache access."""
        return self._cache
