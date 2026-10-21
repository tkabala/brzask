"""What the demo instance is made of: invented sources, interests and stories.

Every name here is made up and every host is under `.example`; story titles
are built from a subject and an event of the same topic, so a month of
digests needs no real headline.
"""

from dataclasses import dataclass

from brzask.db.models import SourceOrigin, SourceStatus


@dataclass(frozen=True, slots=True)
class DemoSource:
    name: str
    host: str
    topic: str | None = None  # what it publishes; None for none in the demo month
    status: SourceStatus = SourceStatus.ACTIVE
    origin: SourceOrigin = SourceOrigin.MANUAL
    origin_detail: str | None = None
    note: str | None = None
    error: str | None = None  # the fetch error it fails with
    permanent: bool = False  # the error says the feed is gone


@dataclass(frozen=True, slots=True)
class DemoInterest:
    topic: str
    keywords: tuple[str, ...]
    notes: str = ""
    active: bool = True


@dataclass(frozen=True, slots=True)
class Topic:
    """Stories of one interest: `{s}` in an event is replaced by a subject."""

    name: str
    subjects: tuple[str, ...]
    events: tuple[tuple[str, str], ...]  # (title, summary)
    why: tuple[str, ...]  # why it matters, taken in turn


RELEASES = "Release Radar"

SOURCES = (
    DemoSource("Tidewater Data", "tidewater-data.example", "Databases"),
    DemoSource("Query Plans Weekly", "query-plans.example", "Databases"),
    DemoSource("Agent Field Notes", "agent-notes.example", "AI agents"),
    DemoSource("Model Kitchen", "model-kitchen.example", "AI agents"),
    DemoSource("Shelf Server", "shelf-server.example", "Homelab"),
    DemoSource("Two Disks Deep", "two-disks.example", "Homelab"),
    DemoSource("Borrow Checked", "borrow-checked.example", "Rust"),
    DemoSource("Crate Notes", "crate-notes.example", "Rust"),
    DemoSource("Incident Review", "incident-review.example", "Security"),
    DemoSource(RELEASES, "releases.example", None),
    DemoSource("Slow Tech News", "slow-tech.example", error="HTTP 503 Service Unavailable"),
    DemoSource(
        "Old Dispatch",
        "old-dispatch.example",
        status=SourceStatus.DEAD,
        error="HTTP 410 Gone",
        permanent=True,
    ),
    DemoSource(
        "Webinar Wire",
        "webinars.example",
        status=SourceStatus.MUTED,
        note="source review: 41 articles in 30 days, none in the top 15, none opened",
    ),
    DemoSource(
        "Planner Notes",
        "planner-notes.example",
        status=SourceStatus.PENDING,
        origin=SourceOrigin.DISCOVERY,
        origin_detail="searxng",
        note="discovery judge: interest fit 2.6/3, substance 1.7/2",
    ),
    DemoSource(
        "Small Models Weekly",
        "small-models.example",
        status=SourceStatus.PENDING,
        origin=SourceOrigin.VISITED,
        note='You opened "A 4B model that routes tool calls" through Hacker News.',
    ),
    DemoSource(
        "Growth Hacks Daily",
        "growth-hacks.example",
        status=SourceStatus.REJECTED,
        origin=SourceOrigin.DISCOVERY,
        origin_detail="searxng",
        note="discovery judge: interest fit 0.8/3, substance 0.4/2",
    ),
)

INTERESTS = (
    DemoInterest(
        "Databases",
        ("query planner", "replication", "pgvector"),
        "want: releases with benchmarks, planner internals; skip: vendor webinars",
    ),
    DemoInterest(
        "AI agents",
        ("agent", "MCP", "tool use"),
        "want: real deployments and what broke; skip: funding news",
    ),
    DemoInterest("Homelab", ("self-hosting", "NAS")),
    DemoInterest(
        "Rust",
        ("Rust", "cargo"),
        "want: language and compiler changes; skip: crate-of-the-week lists",
    ),
    DemoInterest("Security", ("CVE", "supply chain"), "want: post-mortems of real incidents"),
    DemoInterest("Retro computing", ("emulation",), active=False),
)

TOPICS = (
    Topic(
        "Databases",
        ("Tidepool DB", "Larchbase", "Quartzlite", "pg_fathom", "Ferrous SQL", "Kelpie"),
        (
            (
                "{s} makes asynchronous reads the default",
                "{s} now reads table pages ahead on every sequential scan.",
            ),
            (
                "{s} adds skip scans for multicolumn indexes",
                "Queries that filter on a later index column no longer fall back to a full scan.",
            ),
            (
                "{s} halves replica lag in a new benchmark",
                "Replicas catch up twice as fast under a sustained write load.",
            ),
            (
                "{s} drops its oldest wire protocol",
                "Clients older than five years need an upgrade before the next major release.",
            ),
            (
                "{s} explains a planner regression",
                "A cost-model change slowed some joins; the maintainers show how they found it.",
            ),
            (
                "{s} gets incremental backups",
                "Backups now copy only the pages that changed since the last full one.",
            ),
            (
                "{s} rewrites its vacuum scheduler",
                "Tables are now picked by estimated bloat instead of a fixed threshold.",
            ),
            (
                "{s} publishes its first security audit",
                "An outside audit found two medium issues, both fixed before publication.",
            ),
            (
                "{s} replicates sequences logically",
                "A failover no longer needs a manual sequence reset.",
            ),
            (
                "{s} moves to a yearly release cycle",
                "One major version a year, minor releases every quarter.",
            ),
        ),
        (
            "Matches your notes: a release with numbers, not a webinar.",
            "Planner internals, which your notes ask for.",
            "Changes how upgrades and failovers work for databases you run.",
        ),
    ),
    Topic(
        "AI agents",
        ("Quill Agent", "Harbor", "Lantern", "Skein", "Tern", "Cobble"),
        (
            (
                "{s} runs every tool call in its own sandbox",
                "Each call gets a time and memory limit and no network unless asked.",
            ),
            (
                "{s} writes a failing test before every fix",
                "A team made its coding agent prove the bug before proposing a change.",
            ),
            (
                "A month of {s} in production",
                "What broke after a month of answering real support tickets.",
            ),
            (
                "{s} cuts token use by a third with shorter plans",
                "It plans in short steps and re-plans on failure instead of planning up front.",
            ),
            (
                "A patch series drafted with {s} gets merged",
                "Reviewers kept the series after three rounds of human changes.",
            ),
            (
                "{s} adds a dry run for every action",
                "It now shows what it would change before touching anything.",
            ),
            (
                "Why {s} stopped trusting tool output",
                "A prompt injection arrived through a fetched web page; this is how it was caught.",
            ),
            (
                "{s} routes tool calls with a 4B model",
                "A small model picks the tool; the large one is kept for writing.",
            ),
            (
                "{s} publishes its evaluation suite",
                "The tasks it is measured on are now public, failures included.",
            ),
            (
                "{s} asks before acting outside the sandbox",
                "Sending messages and spending money now need a human yes.",
            ),
        ),
        (
            "A real deployment, the kind your notes ask for.",
            "Shows a failure mode before you hit it yourself.",
            "Practical detail on running agents, not an announcement.",
        ),
    ),
    Topic(
        "Homelab",
        (
            "one mini PC",
            "a three-node cluster",
            "an old laptop",
            "a fanless box",
            "a used workstation",
            "a two-bay NAS",
        ),
        (
            (
                "Twelve services on {s}",
                "A year of mail, photos and home automation, power bill included.",
            ),
            (
                "Backups that restore: a drill on {s}",
                "Restoring from scratch found two services nobody had backed up.",
            ),
            (
                "Getting {s} down to 9 watts at idle",
                "Firmware settings, disk spin-down and one replaced fan.",
            ),
            (
                "Moving photos off the cloud to {s}",
                "The migration took a weekend; the face search took a month.",
            ),
            (
                "What failed first on {s}",
                "A fan, then a disk, then the power supply: three years of failures.",
            ),
            (
                "Reaching {s} from outside without open ports",
                "A small VPN mesh replaced port forwarding and a dynamic DNS script.",
            ),
            (
                "Three dashboards worth keeping for {s}",
                "Disk health, backups and certificates; everything else was noise.",
            ),
            (
                "Upgrading {s} without downtime",
                "Snapshots first, a rollback plan, and the one service that still broke.",
            ),
            (
                "What a UPS really protects on {s}",
                "Two short outages a year and a shutdown script that finally works.",
            ),
            (
                "Local language models on {s}",
                "Which models fit, how fast they answer and what they cost in power.",
            ),
        ),
        (
            "Close to the setup you run at home.",
            "A cheap fix you can try this weekend.",
            "Real numbers from a machine like yours.",
        ),
    ),
    Topic(
        "Rust",
        (
            "the borrow checker",
            "cargo",
            "async closures",
            "the next edition",
            "const generics",
            "rustdoc",
        ),
        (
            (
                "What changes for {s} in the next release",
                "A walk through the merged pull requests that touch it.",
            ),
            (
                "Compile times: {s} gets 20% faster",
                "Most of the time went into one query; caching it helped every crate.",
            ),
            (
                "{s} in a codebase of 400 crates",
                "Where it helped a large team, and where it got in the way.",
            ),
            (
                "The design notes behind {s}",
                "The proposal, the alternatives and why they were rejected.",
            ),
            (
                "Better error messages for {s}",
                "Diagnostics now point at the cause instead of the symptom.",
            ),
            (
                "Teaching {s} to a new team",
                "The exercises that worked and the explanation that made it click.",
            ),
            (
                "The open questions about {s}",
                "Three unresolved issues and who is working on them.",
            ),
            (
                "A soundness bug in {s}, a year later",
                "The minimal reproduction, the fix and why it took so long.",
            ),
            (
                "Tooling around {s} nobody talks about",
                "Linters, editor support and test helpers worth adding.",
            ),
            (
                "Benchmarks: {s} against the C version",
                "Same algorithm, same machine; Rust wins two of three workloads.",
            ),
        ),
        (
            "A language change, which your notes ask for.",
            "Compiler work that will change your build times.",
            "Explains a part of the language you use daily.",
        ),
    ),
    Topic(
        "Security",
        (
            "a CI runner",
            "a package registry",
            "a deploy key",
            "a home router",
            "a browser extension",
            "a base image",
        ),
        (
            (
                "Post-mortem: credentials leaked through {s}",
                "The timeline, the root cause and the three changes made since.",
            ),
            (
                "A supply chain attack through {s}",
                "A malicious update reached a few hundred installs before it was pulled.",
            ),
            (
                "Auditing {s} in an afternoon",
                "A checklist that found one real problem and two false alarms.",
            ),
            (
                "Why rotating {s} took three weeks",
                "Every place the old secret had been copied to, found one at a time.",
            ),
            (
                "A critical bug in {s}, explained",
                "What the advisory says, what it leaves out and who needs to act.",
            ),
            (
                "Signing {s} end to end",
                "Keyless signatures, verification on install and what is still not covered.",
            ),
            (
                "Five settings that harden {s}",
                "Defaults that ship open and the lines that close them.",
            ),
            (
                "The signs that {s} was compromised",
                "The logs that showed it, and the ones nobody had kept.",
            ),
            (
                "Least privilege for {s} in practice",
                "Permissions removed one at a time until something broke.",
            ),
            (
                "A threat model of {s} for a small team",
                "Who would attack it, how, and what is worth defending.",
            ),
        ),
        (
            "A post-mortem of a real incident, as your notes ask.",
            "Affects tools you depend on; check whether you need to act.",
            "Concrete steps rather than a vendor report.",
        ),
    ),
)
