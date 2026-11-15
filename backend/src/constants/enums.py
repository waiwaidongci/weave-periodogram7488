from enum import StrEnum
class Role(StrEnum):
 ADMIN='admin'
 ANALYST='analyst'
 VIEWER='viewer'
class RunStatus(StrEnum):
 QUEUED='queued'
 RUNNING='running'
 COMPLETED='completed'
 FAILED='failed'
class NoteStatus(StrEnum):
 DRAFT='draft'
 APPROVED='approved'
 REJECTED='rejected'
class WatchRevisionStatus(StrEnum):
 RUNNING='running'
 PUBLISHED='published'
 SUPERSEDED='superseded'
 FAILED='failed'
class WatchTaskStatus(StrEnum):
 PENDING='pending'
 DISPATCHED='dispatched'
 COMPLETED='completed'
 FAILED='failed'
