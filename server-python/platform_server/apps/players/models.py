"""玩家封禁记录。

**只落在管理平台自己的库**（`db_scmj_admin` 的 `players_playerban` 表），
不往玩家库写任何一行——这是 `../AGENTS.md` §2 第一条与第五条的分工：
玩家库只有只读入口（`player_source.py`），可写的东西全在本平台库里。

为什么是"追加记录"而不是"改一行状态"
--------------------------------------

每次封禁 / 解封都**新增一行**，当前状态由"最新那一行"推导（`current_record()` /
`banned_player_ids()`）。这样：

* 封禁历史天然完整，运营能看到"谁在什么时候因为什么封了他"，不需要另建审计表；
* 不会有"更新状态时把上一条原因覆盖掉"的信息丢失；
* 玩家 ID 上用 `Max(id)` 取最新，逻辑简单且事务安全。

代价是这张表会持续增长。它只记录**发生过封禁动作的玩家**，
量级远小于玩家总数；真到了需要归档的时候，再加清理任务也不影响接口契约。
"""

from __future__ import annotations

from typing import Any

from django.db import models
from django.db.models import Max, Q
from django.utils import timezone


class PlayerBan(models.Model):
    """一条封禁 / 解封流水，兼作当前封禁状态的唯一来源。"""

    class Action(models.TextChoices):
        """操作类型。"""

        BAN = "ban", "封禁"
        UNBAN = "unban", "解封"

    #: 玩家 ID（`t_users.userid`）。不建外键——那张表在**另一个库**里，
    #: 跨库外键在 MySQL 上根本不合法，Django 也不该知道玩家表的存在。
    player_id = models.PositiveIntegerField("玩家ID", db_index=True)

    #: 操作时的账号与昵称**快照**：玩家改名/换账号后，历史记录仍要能读懂。
    account = models.CharField("玩家账号", max_length=64, blank=True, default="")
    player_name = models.CharField("玩家昵称", max_length=64, blank=True, default="")

    action = models.CharField("操作", max_length=16, choices=Action.choices)
    reason = models.CharField("原因", max_length=200, blank=True, default="")

    #: 操作人。管理员被删时不级联删记录（`SET_NULL`），另存一份账号名快照。
    operator = models.ForeignKey(
        "accounts.AdminUser",
        verbose_name="操作人",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="player_bans",
    )
    operator_name = models.CharField("操作人账号", max_length=150, blank=True, default="")

    #: 封禁到期时间；`None` 表示永久封禁。解封记录不用这个字段。
    expires_at = models.DateTimeField("自动解封时间", null=True, blank=True)

    created_at = models.DateTimeField("操作时间", default=timezone.now, editable=False)

    class Meta:
        db_table = "players_playerban"
        verbose_name = "玩家封禁记录"
        verbose_name_plural = "玩家封禁记录"
        ordering = ("-created_at", "-id")
        indexes = [
            # 列表页要按玩家取"最新一条"，这个组合索引就是为它建的。
            models.Index(fields=["player_id", "-created_at"], name="idx_player_ban_time"),
            models.Index(fields=["action", "-created_at"], name="idx_player_ban_action"),
        ]

    def __str__(self) -> str:
        return f"{self.account or self.player_id} {self.get_action_display()}"

    # ------------------------------------------------------------ 状态判断

    @property
    def is_effective(self) -> bool:
        """这条记录是否代表"此刻仍处于封禁中"。"""
        if self.action != self.Action.BAN:
            return False
        if self.expires_at is None:
            return True
        return self.expires_at > timezone.now()

    # ------------------------------------------------------------ 查询助手

    @classmethod
    def _latest_ids(cls, *, player_ids: list[int] | None = None) -> list[int]:
        """取每个玩家最新一条流水的 id（表是有序追加的，所以是 `Max(id)`）。"""
        queryset = cls.objects.all()
        if player_ids is not None:
            queryset = queryset.filter(player_id__in=player_ids)
        return list(
            queryset.values("player_id")
            .annotate(latest_id=Max("id"))
            .values_list("latest_id", flat=True)
        )

    @classmethod
    def current_records(cls, player_ids: list[int]) -> dict[int, PlayerBan]:
        """批量取"每个玩家的最新一条流水"。

        列表页用它在一次查询里补齐封禁状态，避免按行查库（N+1）。

        :param player_ids: 当前页的玩家 ID。
        :return: `{player_id: 最新记录}`；没有记录的玩家不在字典里。
        """
        ids = sorted({int(item) for item in player_ids})
        if not ids:
            return {}
        latest = cls._latest_ids(player_ids=ids)
        if not latest:
            return {}
        records = cls.objects.filter(id__in=latest).select_related("operator")
        return {int(record.player_id): record for record in records}

    @classmethod
    def current_record(cls, player_id: int) -> PlayerBan | None:
        """取单个玩家的最新一条流水。"""
        return cls.current_records([player_id]).get(int(player_id))

    @classmethod
    def banned_player_ids(cls) -> set[int]:
        """当前仍在封禁中的玩家 ID 集合（永久封禁 + 尚未到期的限时封禁）。"""
        latest = cls._latest_ids()
        if not latest:
            return set()
        rows = (
            cls.objects.filter(id__in=latest, action=cls.Action.BAN)
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
            .values_list("player_id", flat=True)
        )
        return {int(player_id) for player_id in rows}

    @classmethod
    def banned_count(cls) -> int:
        """当前封禁中的玩家数。"""
        return len(cls.banned_player_ids())

    @classmethod
    def is_banned(cls, player_id: int) -> bool:
        """该玩家此刻是否处于封禁中。"""
        record = cls.current_record(player_id)
        return record is not None and record.is_effective

    @classmethod
    def history(cls, player_id: int, limit: int = 50) -> list[PlayerBan]:
        """该玩家的封禁流水的倒序列表。"""
        return list(cls.objects.filter(player_id=player_id).select_related("operator")[: max(limit, 1)])

    # ------------------------------------------------------------ 序列化

    def as_payload(self) -> dict[str, Any]:
        """给前端的状态块（`player_source` 的行 + 这个就是列表的一行）。"""
        return {
            "id": self.id,
            "action": self.action,
            "action_display": self.get_action_display(),
            "reason": self.reason,
            "operator_name": self.operator_name,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }
