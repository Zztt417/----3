"""长期记忆模块：基于 Chroma 向量库 + bge-small-zh-v1.5 的语义记忆（按会话隔离）。"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

# 向量库集合名
COLLECTION_NAME = "long_term_memory"

# 记忆类型（写入 metadata 的 type 字段）
MEMORY_TYPES = ("fact", "preference", "conclusion")
DEFAULT_MEMORY_TYPE = "fact"

# metadata 字段名
FIELD_SESSION = "session_id"
FIELD_TIMESTAMP = "timestamp"
FIELD_TYPE = "type"
FIELD_TAGS = "tags"


def _now() -> str:
    """返回当前时间的 ISO 字符串（精确到秒）。

    返回:
        形如 "2026-09-27T15:30:45" 的时间戳。
    """
    return datetime.now().isoformat(timespec="seconds")


class LongTermMemory:
    """长期记忆：把重要事实写入向量库，按语义检索回忆。

    每条记忆的 metadata 至少包含：``session_id`` / ``timestamp`` / ``type``。
    检索默认只在本会话内进行（``where={"session_id": ...}``），实现会话间隔离；
    跨会话检索必须显式调用 :meth:`search_cross_session`。

    嵌入在本机计算（bge-small-zh-v1.5），不依赖外部 embedding API。
    """

    def __init__(
        self,
        persist_dir: str | Path,
        model_dir: str | Path,
        top_k: int = 3,
        collection_name: str = COLLECTION_NAME,
    ) -> None:
        """初始化（会加载嵌入模型与向量库）。

        参数:
            persist_dir: Chroma 持久化目录。
            model_dir: 本地 bge 模型目录。
            top_k: 默认检索条数。
            collection_name: 集合名。
        """
        import chromadb
        from chromadb.utils import embedding_functions

        # 指向本地模型目录，离线推理
        self._embedding = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=str(model_dir)
        )
        self._client = chromadb.PersistentClient(path=str(persist_dir))
        self._collection_name = collection_name
        self._collection = self._client.get_or_create_collection(
            name=collection_name, embedding_function=self._embedding
        )
        self.top_k = top_k

    # ---------- 写入 ----------

    def add(
        self,
        content: str,
        session_id: str,
        mem_type: str = DEFAULT_MEMORY_TYPE,
        tags: str = "",
    ) -> str:
        """写入一条长期记忆。

        参数:
            content: 记忆正文（应自包含、脱离上下文也能读懂）。
            session_id: 归属会话 ID——检索时据此隔离。
            mem_type: 记忆类型，取值见 MEMORY_TYPES；非法值回退为默认类型。
            tags: 可选标签，便于将来做分类过滤。

        返回:
            该条记忆的 ID。
        """
        doc_id = uuid.uuid4().hex
        metadata: dict[str, Any] = {
            FIELD_SESSION: session_id,
            FIELD_TIMESTAMP: _now(),
            FIELD_TYPE: mem_type if mem_type in MEMORY_TYPES else DEFAULT_MEMORY_TYPE,
        }
        if tags:
            metadata[FIELD_TAGS] = tags
        self._collection.add(ids=[doc_id], documents=[content], metadatas=[metadata])
        return doc_id

    # ---------- 检索 ----------

    def search(self, query: str, session_id: str, top_k: int | None = None) -> list[str]:
        """在**当前会话内**按语义检索长期记忆。

        参数:
            query: 查询文本（通常是用户本轮输入）。
            session_id: 当前会话 ID；检索范围严格限定在该会话内。
            top_k: 检索条数，默认用实例的 top_k。

        返回:
            命中的记忆文本列表（无命中返回空列表）。
        """
        if not query.strip():
            return []
        result = self._collection.query(
            query_texts=[query],
            n_results=max(1, top_k or self.top_k),
            where={FIELD_SESSION: session_id},
            include=["documents", "metadatas"],
        )
        documents = result.get("documents") or [[]]
        return [doc for doc in documents[0] if doc]

    def search_cross_session(
        self,
        query: str,
        exclude_session_id: str | None = None,
        top_k: int | None = None,
    ) -> list[tuple[str, str]]:
        """**跨会话**按语义检索长期记忆（仅在用户显式要求时使用）。

        参数:
            query: 查询文本。
            exclude_session_id: 要排除的会话 ID（通常是当前会话），避免重复；
                None 表示不排除任何会话。
            top_k: 检索条数，默认用实例的 top_k。

        返回:
            (记忆文本, 来源会话 ID) 列表；无命中返回空列表。
        """
        if not query.strip():
            return []
        where: dict[str, Any] | None = None
        if exclude_session_id:
            where = {FIELD_SESSION: {"$ne": exclude_session_id}}
        result = self._collection.query(
            query_texts=[query],
            n_results=max(1, top_k or self.top_k),
            where=where,
            include=["documents", "metadatas"],
        )
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        hits: list[tuple[str, str]] = []
        for index, doc in enumerate(documents):
            if not doc:
                continue
            meta = metadatas[index] if index < len(metadatas) else {}
            source = str((meta or {}).get(FIELD_SESSION) or "未知会话")
            hits.append((doc, source))
        return hits

    # ---------- 统计与维护 ----------

    def count(self, session_id: str | None = None) -> int:
        """统计记忆条数。

        参数:
            session_id: 指定会话时只统计该会话；None 表示统计全部。

        返回:
            条数。
        """
        if session_id is None:
            return self._collection.count()
        got = self._collection.get(where={FIELD_SESSION: session_id}, include=["metadatas"])
        return len(got.get("ids") or [])

    def delete_session(self, session_id: str) -> int:
        """删除某会话的全部长期记忆。

        参数:
            session_id: 会话 ID。

        返回:
            被删除的记忆条数。
        """
        removed = self.count(session_id)
        if removed:
            self._collection.delete(where={FIELD_SESSION: session_id})
        return removed

    def assign_orphans(self, session_id: str) -> int:
        """把缺少 ``session_id`` 的历史记忆归入指定会话。

        升级到「按会话隔离」之前的记忆没有 session_id，会因此检索不到。
        这里做一次性回填，避免静默丢数据。

        参数:
            session_id: 要归入的会话 ID。

        返回:
            回填的记录条数。
        """
        got = self._collection.get(include=["metadatas"])
        ids = got.get("ids") or []
        metadatas = got.get("metadatas") or []
        orphan_ids: list[str] = []
        fixed: list[dict[str, Any]] = []
        now = _now()
        for index, doc_id in enumerate(ids):
            meta = dict(metadatas[index] or {}) if index < len(metadatas) else {}
            if meta.get(FIELD_SESSION):
                continue
            meta[FIELD_SESSION] = session_id
            meta.setdefault(FIELD_TIMESTAMP, now)
            meta.setdefault(FIELD_TYPE, DEFAULT_MEMORY_TYPE)
            orphan_ids.append(doc_id)
            fixed.append(meta)

        if orphan_ids:
            self._collection.update(ids=orphan_ids, metadatas=fixed)
        return len(orphan_ids)

    def reset(self) -> None:
        """清空全部长期记忆（所有会话）。"""
        self._client.delete_collection(self._collection_name)
        self._collection = self._client.get_or_create_collection(
            name=self._collection_name, embedding_function=self._embedding
        )


def create_long_term_memory(persist_dir: str, model_dir: str, top_k: int) -> LongTermMemory | None:
    """尝试创建长期记忆；任何前置条件不满足时返回 None（降级，不抛异常）。

    参数:
        persist_dir: Chroma 目录。
        model_dir: 本地 bge 模型目录。
        top_k: 默认检索条数。

    返回:
        LongTermMemory 实例；依赖缺失或模型不存在时返回 None。
    """
    if not Path(model_dir).exists():
        print(
            f"[记忆] 未找到嵌入模型目录 {model_dir}，长期记忆已禁用。"
            "请先运行：python setup_memory.py",
            file=sys.stderr,
        )
        return None
    try:
        return LongTermMemory(persist_dir=persist_dir, model_dir=model_dir, top_k=top_k)
    except ImportError as exc:
        print(
            f"[记忆] 缺少依赖（{exc}），长期记忆已禁用。请运行：pip install -r requirements.txt",
            file=sys.stderr,
        )
        return None
    except Exception as exc:  # 模型损坏 / 目录不可写等
        print(f"[记忆] 长期记忆初始化失败（{type(exc).__name__}: {exc}），已禁用。", file=sys.stderr)
        return None
