---
source: pdfs
silo: pdfs
source_id: framework catalog for an AI powered infrastructure advisor
url: ""
created_at: "2026-09-21T07:13:12.054409+00:00"
ingested_at: "2026-09-21T08:39:31.814620+00:00"
tags: [pdf]
author: ""
content_hash: f8f0e8295123ef8d9908a927e15dba23518b6373006db7d07d4abf5af16a7102
---
> # Framework Catalog for an Al-Powered  # Infrastructure Advisor  ##### The constitution five fixed parts  "One catalog u...

# Framework Catalog for an Al-Powered

# Infrastructure Advisor

##### The constitution five fixed parts

"One catalog underlies every scenario” only means something if the catalog is a concrete structure, not a vibe. Here it is:

The pillar set a fixed list of quality dimensions everything gets scored against: Security, Reliability,

Performance Efficiency, Cost, Operational Excellence/Maintainability, Compatibility, Sustainability. This is the union of ISO 25010's characteristics and the cloud WAF pillar taxonomies. Doesn't change per scenario. The gating layer compliance/security frameworks that run first and eliminate non-compliant options

before any scoring happens (NIST CSF, CIS Controls, ISO 27001, SOC 2/PCI-DSS/HIPAA, data residency).

Constant. The estimation method how "codebase + candidate infra" becomes an actual number per pillar. See

Section 1— this is the layer that needs both structural and quantitative analysis. Constant in method; the

specific evidence it consumes varies by scenario.

The trade-off resolution method ATAM-style surfacing of conflicts instead of a black-box "best" answer.

Constant.

The feedback loop SRE/DORA metrics plus FinOps rightsizing, correcting the model post-deployment.

Constant. Section 3's scenario table never modifies (1), (2), (4), or (5). It only ever modifies 3 which additional

evidence feeds the estimation, and how the pillar weights get set. A migration doesn't get a different rulebook; it gets different inputs into the same rulebook.

###### 1. Mapping frameworks to your pipeline

Frameworks/methods to draw

Pipeline p stage 8! Job

on

Twelve-Factor ISO/IEC App,

Classify lassify workload workload archetype, archet detect tect

\\sofiEC 50552021

1a. Structural code analysis 4 > vality/risk he p posture, extract service

’ (CISQ), Domain-Driven Design,

pology

C4 Model

1b. Quantitative resource & capacity Convert structural signals into Complexity/hotspot metrics as

estimation actual proxies, dynamic profiling, load

testing, Little's Law, Universal

-----

Frameworks/methods to draw Pipeline stage Job

on

| CPU/memory/throughput/latency | Scalability Law, queueing |
|---|---|
| requirements | theory, historical production telemetry |

NIST CSF 2.0, CIS Controls v8.1, Hard filters applied before scoring

Requirement extraction [ constraint ISO/IEC 27001:2022,SOC 2 /

eliminate non-compliant options gating PCI-DSS [ HIPAA, NIST SP 800-

outright

207 (Zero Trust)

Infra option scoring

(performance/security/reliability/ops)

Cost scoring

Trade-off resolution

Recommendation validation / feedback loop

Why 1a and 1b are split, and why that matters: they

you to "minimal cost resources that meet the metrics.”

Ta (structural) tells you about code quality and risk, not runtime resource consumption. ISO/IEC 5055 actual ISO standard behind "100+ automatable code metrics” 2021. It operationalizes four of ISO 25010's characteristics (Security, Reliability, Performance Efficiency,

Maintainability) into dozens of countable structural weaknesses detected directly from

kind of rule sets static analyzers like SonarQube implement. It's genuinely useful: it tells structural performance/reliability weaknesses." It does not tell to handle 500 req/s at p99 under 200ms." Structural quality and runtime resource identical.

Rank surviving candidates against 1a+1b output

Rank by cost efficiency and commitment fit against 1b's resource FinOps Framework estimate

When no option dominates on all

pillars, surface the trade-off instead ATAM, QAW (SEI) of forcing a single "best" answer

Post-deployment monitoring targets, learn from outcomes

Union of

AWS/Azure/GCP/OCI/IBM Well-

Architected pillar taxonomies, 1SO 25010 characteristics, CSA CCM

SRE (SLIs/SLOs/error budgets), DORA metrics, Golden

Signals/RED/USE, OpenTelemetry semantic

conventions are different kinds of analysis, and neither alone gets the

is CISQ's work, adopted as an ISO standard in

source code the

you “this module has you "this service needs 2 vCPU and 4GB RAM

cost are correlated, not

-----

1b (quantitative) is where actual sizing numbers come from, and it's an empirical/mathematical problem, not a

static-analysis lookup: Complexity/hotspot signals (cyclomatic complexity, dependency fan-out) are weak directional proxies at

best.

Dynamic profiling under synthetic load gives real per-request resource cost that static analysis can't produce. Load/performance testing, calibrated to expected traffic shape, produces empirical throughput-perinstance curves. Historical production telemetry, when it exists, is the single most reliable signal available and should always outrank the others. Little's Law (L AW) and the Universal Scalability Law turn "X resources handle Y throughput at Z latency"

=

into "how many resources do | need, and where do returns diminish” the USL specifically identifies the

minimal-cost point, since it models where added resources stop paying off due to contention/coherency overhead. So: the qualitative frameworks (ISO 25010, WAF pillars, Twelve-Factor) tell your tool what to measure and

what "good" means per pillar. They don't compute the numbers. For a genuinely new/unobserved codebase, any sizing estimate produced without load testing or telemetry is necessarily a band, not a precise figure

that's a limit of the problem, not of framework choice. A well-designed tool should emit an initial estimate with a stated confidence level, require load-test or canary validation before treating it as final, then feed real

telemetry back through the FinOps rightsizing loop.

When dynamic profiling and load testing genuinely aren't available (the likely default state for your tool, since it's often estimating before anything is deployed), fall back through these tiers in order of evidence

strength, not convenience:

Isolated micro-benchmarking still dynamic, but doesn't require full infra or realistic traffic simulation.

Execute hot-path functions in a sandbox with synthetic inputs using language-native benchmark harnesses (Go's JMH for Java, [pytest-benchmark], etc.). This is the strongest signal available short of full load

a

test, and it's genuinely automatable your tool can identify hot paths via 1a's complexity/hotspot signals,

then benchmark just those in isolation. Reference-class benchmarking borrow empirical data from comparable systems instead of the system

itself. Public standardized benchmarks (e.g., TechEmpower Framework Benchmarks, which continuously

compares throughput/latency across languages, frameworks, and DB drivers under identical load) give a

defensible cost-per-request prior for a given stack. If the organization runs any other service on a similar

stack, its telemetry is a usable prior too, even if it's not the exact codebase.

Analytical/first-principles modeling the formal discipline is "workload characterization" (see Menascé &

capacity-planning literature): extract algorithmic complexity where feasible, estimate operation counts from the call graph and data model (e.g, "this endpoint makes N DB round trips per request”), and

combine with known per-operation unit costs. This is bottom-up cost accounting rather than measurement, so it's the weakest tier but still better than a guess.

-----

Conservative provisioning + fast production correction paired with all of the above, not a replacement for them. Given real uncertainty, the standard industry answer isn't "nail the number in advance," it's "provision with headroom, autoscale aggressively on live signals, and treat the first period in production as the load test." Every estimate should carry both a confidence band and a label for which tier produced it, so

downstream scoring can apply a safety margin proportional to how weak the evidence is a Tier 1 number

and a Tier 3 guess should never be weighted the same.

Ideas worth borrowing from deep code-review tooling and developer-productivity research both

fields have already solved adjacent versions of "estimate something real from a codebase without running it":

Code-graph-scoped estimation (from CodeRabbit). CodeRabbit builds a deterministic dependency graph tracing exactly which files/functions a change touches, cross-file and cross-repo, rather than reasoning

about "the codebase" in the abstract. Apply the same move to 1b: instead of estimating a whole service's

resource needs at once, trace the actual call graph per request path (this endpoint > these N functions >

these M DB/external calls) and estimate at that scope. It turns Tier 3's "guess the operation count” into "count the operations in the actual traced path" meaningfully sharper.

Reachability analysis (from CodeRabbit's security scanning). CodeRabbit doesn't just flag a vulnerability

it checks whether the vulnerable path is actually reachable under real conditions. The same check matters

for sizing: a structurally expensive-looking function that's dead code or an unreachable edge case shouldn't

drive provisioning. Reachability, not just complexity, should gate whether a hot-looking path counts.

Ensemble over any single estimator (from CodeRabbit's multi-model orchestration and Weave's stacking multiple Al reviewers before a human sees a PR). Both tools exist because no single tool/model catches everything they deliberately combine several imperfect signals rather than trusting one. That's the same

argument for combining complexity metrics + dependency-graph tracing + reference-class benchmarks

rather than picking one and calling it done.

Learned calibration from outcomes (from incorporation of reviewer corrections into

future reviews). Every time a Tier 1-3 estimate is later checked against real telemetry (via the feedback

loop), store the (estimate, actual) pair and use it to correct systematic bias per language, framework, or

code pattern rather than treating each new estimate as independent of what you've already learned was

wrong last time.

Triangulation-as-diagnostic, not just averaging (from the DORA/SPACE/DevEx research line Forsgren,

Storey, Noda, Greiler). Their core methodological argument is that system data and perceptual data should

be used complementarily, and when they disagree, the disagreement itself is the signal worth investigating, not something to average away. Applied here: when a static/analytical estimate and a reference-class benchmark diverge sharply, that divergence should trigger a lower-confidence flag or a human-review prompt not get silently blended into one number.

Prefer hard-to-game signals (also from that research line). Forsgren notes DORA's four keys are valued

partly because they resist gaming, unlike raw activity counts (PRs, commits). The equivalent discipline here: ground estimates in structural/behavioral signals (call graphs, actual complexity) rather than superficial ones (LOC, function count) that a differently-written but equally expensive codebase could easily dodge. State the method's scope explicitly (also from that line). DORA is explicit that it only covers commit-torelease, not everything before or after. Your estimation layer should be equally explicit about what it covers

-----

e.g. steady-state request-serving load and what it doesn't batch jobs, cold starts, seasonal spikes

---

rather than implying one number covers everything. Context engineering [ 1:1 code-to-context ratio (CodeRabbit). It pairs every line under review with equalweight surrounding context (history, dependency graph, prior PR patterns) rather than judging code in isolation. Score a function's cost the same way paired with how structurally similar code performed

historically, not alone.

Ephemeral sandboxes, spun up and torn down per check (CodeRabbit). A good architectural template for

Tier 1 micro-benchmarking: cheap, isolated, on-demand, persistent benchmarking environment to

no

maintain.

Depth that adapts to context (CodeRabbit). It runs a lighter pipeline for IDE-time checks and a deeper one

for PR-time review, with different model weighting for each. Size differently for a quick exploratory check than for a final pre-deployment recommendation.

Explainable derivation trails (CodeRabbit). It ships a walkthrough and diagram alongside findings, not just a

verdict. An estimate should ship with a human-readable "here's how | got this number," not just the number

directly reduces the Cognitive Load dimension below.

Crawl-before-walk build order (Weave). Their own advice: prove value with one tool before stacking more. Get one estimation tier working well before adding the next rather than building the full ensemble upfront. Round-count as its own signal (Weave). They track how many review rounds a PR goes through to flag bottlenecks. The equivalent: workload types that need many calibration rounds before an estimate stabilizes

are worth flagging as inherently hard to estimate.

The DevEx framework’s three dimensions (Noda, Storey, Forsgren, Greiler), applied directly:

Feedback Loops the emphasis is on loop speed, not just existence. That's the real argument for

Tier 1 waiting slower, precise measurement: fast feedback compounds.

over on a more

Cognitive Load applies to your tool's output, not just its input. A recommendation with five conflicting

signals dumped on the user adds load; a synthesized recommendation with trade-offs surfaced ATAM-style

reduces it. Flow State argues for defaulting to reasonable assumptions and only interrupting the user when confidence

is genuinely low, rather than asking for input at every ambiguity.

Theory of Constraints (Forsgren). Find the actual bottleneck resource CPU vs. memory vs. I/O vs. network

rather than assuming a uniformly balanced profile and scaling everything together.

Metric validity as a discipline, not an assumption (Forsgren/Storey's psychometric framing). A complexity metric should be empirically checked against your own outcome data before you trust it

validity isn't inherited just because a metric is popular elsewhere.

Lessons from the 2026 Al code-review landscape (Greptile, Cursor Bugbot, Macroscope) this category

converged independently on much of the same architecture, which is itself a validation signal:

AST-first parsing, embed summaries rather than raw text (Greptile). Parse via tree-sitter into an AST,

generate natural-language docstrings per node, embed those meaningfully better semantic retrieval than

embedding docs. Apply the the infra corpus's structured files, not just

raw source or raw same move to prose.

Agentic multi-hop retrieval (Greptile). Retrieval isn't one-shot an agent evaluates result relevance and

follows references outward through the graph. Refines Section 5: let the retrieval agent chase references

-----

rather than stopping at the first hit. The deep-vs-shallow tradeoff is real and measured, not hypothetical. Greptile's full-context approach catches substantially more issues than diff-only tools in independent benchmarks, at the cost of speed,

price, and false-positive rate. Confirms a genuine two-speed design (fast/shallow, slow/deep) rather than picking one universally.

Fixed pipeline > agentic was Cursor Bugbot's single biggest quality win when they rebuilt it in late 2025

the agent now decides dynamically where to dig deeper instead of running a fixed sequence of passes. Validates making tier-selection in 1b dynamic rather than a fixed waterfall always run to completion. Learned Rules (Bugbot). Passively watches how humans react to and correct its suggestions as an implicit

calibration signal sharper and cheaper than requiring explicit structured feedback.

Diff-level caching (Bugbot). Recognizes identical content it's already processed and skips redundant work

the same content-hash discipline as Section 5's re-embedding answer, generalized across the whole

pipeline. Resolution/acceptance rate as the real quality metric, not raw findings issued. Bugbot tracks how often

developers actually act on a flag, not just how many it raises. Track how often engineers accept vs. override a

sizing recommendation, not just how many recommendations get made.

Autofix spawns an isolated agent to empirically test a fix before proposing it. A concrete precedent for Tier 1: don't just heuristically estimate spin up the sandbox and check.

Live external knowledge lookup during analysis, not stale training knowledge (Macroscope). It queries current library documentation via search API mid-review specifically because model training data goes stale and library performance characteristics shift across versions cut their false-positive rate 55%. Referenceclass benchmarks should be fetched fresh at estimation time, not assumed from memory.

Business/ticket context, not just code (Macroscope). Pulls Linear/Jira context to understand intent and expected scale behind a change. “Internal admin tool, <10 users" vs. "public checkout API" should shape a

resource estimate as much as code structure does. Precision and detection rate tracked as two separate numbers, never blended into one score. Report

confidence/precision and coverage/detection separately for every estimate, rather than one composite figure that hides which one is weak.

Hotspot analysis: complexity x change-frequency (CodeScene). Code that's both complex and frequently changing is disproportionately where things go wrong research backing this shows hotspots account for a

large share of defects despite being a small fraction of the codebase. Apply the same lens to sizing confidence: lower confidence, and concentrate limited micro-benchmarking budget, on code that's both

complex and still actively churning.

Full spectrum of depth tiers, all non-blocking (Claude Code). runs at multiple effort levels,

and adds a deliberately slow 30-minute tier every tier runs as a background agent so heavy

analysis never floods the main reasoning thread. Extend the fast/deep dual-tier idea to a fuller spectrum, and keep every tier isolated from whatever thread is making the actual recommendation. Multi-repo reasoning is now baseline, not a stretch feature (Codex, shipped cross-repo review in July

2026). Directly relevant since the infra database is itself multiple repos the estimation and scoring layers

should assume cross-repo reasoning as a default capability, not bolt it on later.

-----

Config-source consistency across modes a real cautionary example, not hypothetical. Claude Code's local review but not [ReviEw.md], a documented mismatch between its own modes. Every

depth tier in your pipeline should read from the same rules/config source, or the divergence should be loud

and intentional, not accidental.

Implicit signal capture from every override, not explicit feedback forms (Command Code's "taste" system). It treats every accept, reject, and edit as a training signal automatically, distilling it into a humanreadable, portable profile that can be shared across a team. Their framing is worth borrowing directly: "rules decay, taste compounds" don't hand-write static heuristics for calibration; let an evidence-weighted

profile emerge from real correction signals and stay current on its own.

This is the part worth building deliberately either way: most tools in this space hardcode scoring logic per provider. A cleaner design tags every entry in your infrastructure database (cloud services, observability

platforms, tooling) against the same pillar taxonomy then your scoring engine becomes a weighted

match against 1a/1b output rather than a growing pile of if/else provider logic.

###### 2. Master framework catalog

Universal quality & architecture models

ISO/IEC 25010:2023 the closest thing to a true vendor-neutral "well-architected” standard. Nine

characteristics: Functional Suitability, Performance Efficiency, Compatibility, Interaction Capability,

Reliability, Security, Maintainability, Flexibility, Safety. AWS | Azure | GCP | OCI | IBM Well-Architected Frameworks provider-branded, but the underlying pillar

taxonomy (security, reliability, performance, cost, operations, sustainability) is now a de facto industry template. For a provider-agnostic tool, use the union of pillars across all of them as your generic checklist, and

treat each provider's specific guidance as the "how" once a candidate provider is shortlisted not as the

"what." ATAM | QAW (Software Engineering Institute, Carnegie Mellon) the formal method for evaluating

architecture against competing quality attributes (performance vs. security vs. cost vs. modifiability). This is literally the trade-off engine your tool needs to emulate when frameworks disagree. Code-level measurement & capacity estimation ISO/IEC 5055:2021 (CISQ / OMG) the standard behind "100+ automatable code metrics." Measures

structural weaknesses across four ISO 25010 characteristics (Security, Reliability, Performance Efficiency,

Maintainability) directly from source code. Structural/static a quality and risk signal, not a runtime

resource predictor. Cyclomatic complexity, Halstead measures, dependency fan-in/fan-out classic complexity metrics;

weak proxies for resource intensity, useful mainly for flagging hotspots worth profiling.

Little's Law (L AW) the foundational queueing relationship between concurrency, arrival rate, and

=

latency; translates a target throughput/latency SLO into required concurrency or instance count.

-----

Universal Scalability Law (Neil Gunther) models throughput vs. concurrency accounting for contention and coherency delay; identifies the point of diminishing returns the actual "minimal cost that still meets the metric” point.

Queueing theory (M/M/1, M/M/c models) underlies most capacity-planning math for request-serving systems. Load/performance testing + dynamic profiling practice rather than a named framework, but the

empirical layer static analysis can't substitute for.

Production telemetry analysis when available, the highest-confidence input of all; what FinOps

rightsizing operates on once a workload is live. TechEmpower Framework Benchmarks a continuously-run, standardized public benchmark comparing

throughput/latency across languages, frameworks, and DB drivers. Useful as a reference-class prior when

you can't benchmark the actual codebase.

Menascé & Almeida's workload characterization methodology the academic grounding for analytical

capacity estimation when no live measurement is possible.

##### Security

NIST Cybersecurity Framework (CSF) 2.0 Govern, Identify, Protect, Detect, Respond, Recover. The

reference point most other security frameworks map to. CIS Controls v8.1 18 prioritized controls, provider-agnostic. (CIS Benchmarks are the platform-specific

hardening guides not agnostic themselves, but become relevant once your tool narrows to a specific

cloud/OS/Kubernetes distro.)

ISO/IEC 27001:2022 certification standard.

NIST SP 800-207 (Zero Trust Architecture) architectural model, implementation-agnostic.

OWASP ASVS | Top 10 application-layer, hosting-agnostic.

MITRE ATT&CK + ATT&CK for Cloud matrix) threat modeling reference; conceptually agnostic, subtechniques get provider-specific. CSA Cloud Controls Matrix (CCM) explicitly designed to be cloud-provider-neutral.

Cost FinOps Framework (FinOps Foundation) built for multi-cloud from the outset; as of its 2026 scope

expansion, also covers licensing, and Al workload spend. There's no real competing agnostic cost

framework this is the standard.

##### Reliability & operations

SRE discipline (SLIs/SLOs/error budgets) methodology is provider-agnostic despite Google origin; applies

identically on-prem or on any cloud.

DORA metrics deployment frequency, lead time, change failure rate, MTTR.

CNCF Cloud Native Trail Map / Maturity Model vendor-neutral by design (Linux Foundation project). The staged-adoption pattern transfers to any infra rollout even outside containerized workloads; the specific trail

(containers > CI/CD > orchestration > observability > service mesh) is strongest when the workload is or is becoming cloud-native.

-----

Architecture design & service boundaries The Twelve-Factor App config externalization, statelessness, disposability; good automatable checklist

a

for codebase analysis. C4 Model notation for extracting/documenting architecture at Context/Container/Component/Code levels. TOGAF (ADM) enterprise architecture process, includes explicit stages for evolving/consolidating

architecture over time. Domain-Driven Design (DDD) bounded contexts; useful both for greenfield service design and for

detecting decomposition boundaries in an existing codebase.

##### Observability vocabulary

Four Golden Signals, RED, USE methods what to measure, independent of tooling.

OpenTelemetry CNCF-hosted but explicitly vendor-neutral instrumentation standard.

IT governance

ITIL 4 service management practices.

COBIT IT governance, often paired with NIST CSF and ITIL in enterprise contexts.

##### Compliance overlays

SOC 2, PCI-DSS, HIPAA, GDPR | data residency rules not architecture frameworks per se, but they act as

hard constraints on architecture decisions (encryption, data locality, access control) regardless of cloud choice.

###### 3. Scenario overlays what changes

What's structurally Frameworks/patterns to

Scenario Pillar| reweighting

different layer in

Cloud/platform Decision isn't "best infrain migration the abstract”

path from current target state." Migration

cost/risk must be modeled

alongside steady-state

score.

Gartner/AWS migration "best strategies (SR>7R: Rehost,

Replatform, Repurchase, Refactor/Re-architect, Retire, window; Retain, Relocate); Cloud Adoption Framework staging (assess > mobilize > migrate

-> operate the staging pattern is common across

AWS/Azure/Google's

Operational Excellence/Reliability weighted higher during the transition

cost model must include one-time migration cost,

not just cost

run

-----

What's structurally Frameworks/patterns to

Scenario Pillar reweighting

different layer in

branded CAFs); Strangler Fig Pattern for phased cutover

Mergers & acquisitions |

infra consolidation

Multiple pre-existing

estates, IAM systems, and data models need

reconciling. Decisions are

constrained by existing

contracts/commitments,

not blank-slate

optimization.

TOGAF ADM (built for

evolving/consolidating architecture); Enterprise Integration Patterns (Hohpe

& Woolf); DAMA-DMBOK for data governance/masterdata reconciliation; Zero Trust for merging IAM domains

Compatibility/Interoperability

(ISO 25010 and Security

(identity reconciliation) become primary gates; cost optimization

is secondary to risk reduction

early on

CAP/PACELC theorem;

Reliability & Performance are

|  | You're scoring N services | Fallacies of Distributed |
|---|---|---|
| Distributed | with different | Computing checklist; |
| systems \| | requirements, not one | resiliency patterns — Circuit |
| microservices | workload. Network decomposition reliability becomes a first- class constraint. | Breaker, Bulkhead, Saga (Nygard, Richardson); DDD bounded contexts for |

validating service boundaries

Strangler Fig Pattern;

Fowler's Refactoring catalog & Technical Debt Quadrant;

|  | Goal is reducing technical | Evolutionary Architecture / |  |
|---|---|---|---|
| Refactors \| | debt while keeping the | Fitness Functions (Ford, | Maintainability (ISO 25010 |
| legacy | system running — change- | Parsons, Kua) — especially | becomes a primary scored |
| modernization | safety matters as much as raw infra fit. | relevant since fitness functions are literally automatable architectural | dimension instead of secondary |

checks your tool could run

continuously

Disaster

1SO 22301 (Business Reliability dominates; cost recovery | Redundancy requirements

Continuity Management); optimization constrained by

business dominate the design space.

RTO/RPO modeling required redundancy level continuity

-----

What's structurally Frameworks/patterns to

Scenario Pillar reweighting different layer in

Greenfield applies

| Greenfield vs. | frameworks at design time; | Weighting depends on gap size |
|---|---|---|
| brownfield | brownfield applies them as an audit instrument first. | pillar, not fixed in advance per |

Same catalog, different mode: brownfield = gap

analysis (current pillar scores

vs. target) > remediationpriority ranking

###### 4. Practical notes for your tool's architecture

Tag infrastructure database entries against the same pillar taxonomy, not against provider-specific docs.

Each observability platform, cloud service, or laC tool should carry structured metadata: which ISO 25010 characteristics it scores well/poorly on, which compliance certifications it holds, its cost model type (usagebased, commitment-based, flat), and which CAF/migration stage it fits. This lets scoring be a weighted match

rather than hardcoded per-provider logic. Use hard-gate vs. soft-score separation. Compliance frameworks (SOC 2, PCI-DSS, data residency) should eliminate non-compliant options before scoring even starts they're not "one more weighted factor," they're

Surface trade-offs, don't force a winner. When ATAM-style analysis shows no dominant option

cheapest option fails reliability threshold, most reliable option blows the budget), present the trade-off

matrix to the user rather than silently picking one. This mirrors how ATAM is actually run in practice —as a facilitated trade-off exposure, not an auto-decision. Treat DORA/SRE metrics as the feedback loop, not just an analysis input. Once a recommendation is

deployed, tracking these against the original projection is how the tool's future recommendations improve.

Don't fully trust provider-published specs as ground truth for the infra database but don't try to

independently re-benchmark everything from day one either. Provider specs have known, welldocumented gaps: "up to" language on burstable instance types hides real sustained performance (burstcredit exhaustion on T-series, baseline-vs-burst IOPS on gp2/gp3), multi-tenant noisy-neighbor variance isn't

disclosed at all, and the underlying CPU generation behind an instance-type name can change silently over

time without a rename meaning last year's benchmark of "the same" SKU may no longer be accurate. This is

exactly why independent, third-party benchmarking exists as its own niche Cockroach periodic

Cloud Reports, for instance, run standardized benchmarks across AWS,

Azure, and GCP specifically because vendor spec sheets don't capture delivered performance, and have

repeatedly found real divergence between providers and across years on the same nominal instance classes.

Large infra teams commonly run their own internal "bake-off" benchmarks before adopting a new instance

type at scale for the same reason.

The pragmatic build order: 1 start with provider specs plus existing reputable third-party benchmark datasets as your baseline don't re-derive what's already published and credible; 2 explicitly flag known trust gaps as metadata in your infra database "burstable, sustained performance unverified") rather

-----

than treating provider numbers as certain; 3 as usage concentrates around specific instance types/regions

the ones your tool recommends most invest in your own narrow, continuously-refreshed microbenchmarks for just those. That's both more defensible than relying on generic public data and becomes a

genuine differentiator, since your workload-specific benchmark data isn't something a competitor gets for

free. Treat hardware benchmark data as perishable, on its own refresh cycle, parallel to the workload-telemetry feedback loop in point 4 of the constitution silent hardware refreshes mean a benchmark from 18 months

ago can no longer be trusted as current.

5. Storage & retrieval architecture for the infra database

The database needs two composable layers, and the software layer must contain commercial and opensource implementations on equal footing not open-source-only. Every major provider ships its own

native software/service layer alongside raw compute (AWS RDS, GCP Cloud SQL, Azure Database for PostgreSQL, Oracle Autonomous DB), and these compete directly with open-source equivalents (selfmanaged Postgres, CockroachDB) for the same functional slot. Treating "software stack" as an open-sourceonly category was wrong for any functional need, the candidate set is every implementation that satisfies

it, commercial and open-source together, scored on the same pillars, not commercial-by-default with opensource as a fallback.

One structural asymmetry shapes how the search space has to be built: commercial managed services are

typically coupled to their own provider's compute AWS RDS doesn't run on Hetzner so "AWS EC2 + AWS

RDS" is really one bundled option, not two independently composable pieces. Open-source stacks (Coolify,

k3s, self-managed Postgres/MinlO) are portable across any compute provider. So the decision is nested: first, commercial-managed vs. open-source-self-managed; then, only if open-source, which compute provider hosts it reusing the same compute-scoring machinery already needed elsewhere.

The three comparison axes this requires map onto machinery already established rather than needing new

infrastructure:

Features ISO 25010's Functional Suitability characteristic (cited in Section 2, not yet operationalized until

now). Requires the schema to carry a real feature/capability matrix per entity does it support logical

replication, specific extensions, connection pooling, point-in-time recovery not just numeric specs.

Quality/performance of a given feature, not just its presence the Tier 1-4 estimation framework

(Section 1b) already exists for exactly this. Whether AWS RDS's failover is actually faster than self-managed

Postgres with Patroni is an empirical question, answered the same way any other performance claim in this system gets answered.

Price, priced as total cost in both directions self-managed options carry the operational-overhead cost

already established; commercial services carry their own often-hidden costs a sticker price doesn't show

(egress fees, forced-tier minimums, bundling requirements). Pricing only one side as "total" and the other as

“nominal” rigs the comparison.

-----

Lock-in/restrictiveness this is the constitution's existing Compatibility pillar, not a new dimension;

portability was already in scope, just not wired to this specific comparison before.

These stacks commercial and open-source alike are usually documented in GitHub repos (a provider's

own Terraform provider, an open-source project's own repo), so they fit the git-native pipeline below directly.

The source data is GitHub repos, regularly updated that constraint, plus the mix of numeric specs and

prose guidance inside those repos, means this shouldn't be a single retrieval method. Match the method to

the query type:

Query type Example Right tool Wrong tool

"compute options Structured DB Vector search can't reliably

### Structured/numeric

RAM, SOC (Postgres/SQLite) witha respect exact numeric

filterin 8

2, <$200/mo" real schema and indexes constraints

Keyword/full-text search

"current spec p for Pure vector similarity returns

Exact identifier lookup (BM25) or direct structured

rég.xlarge" gxlarg "close," not "exact"

lookup

"sizing 8 approach PP Hybrid search: BM25 y + Grep P alone misses

### Conceptual/fuzzy

for a write-heavy vector + LLM rerank (what paraphrased/synonymous

g

Postgres service" itself does) guidance

A newly added

Live agentic exploration Novel repo format your infrarepo with an A stale pre-built index that

(grep/glob, Claude Codeparser doesn't handle yet unfamiliar doesn't cover it

style)

structure

"did the rég.xlarge Agent memory / outcomes

The tool's own Mixing it into the main corpus

call for API store, decoupled from the accumulated learning different data, different lifecycle

workloads hold up" reference corpus

On the named options: is areal, actively developed local search engine (Tobi LUtke) that's already hybrid BM25 + vector search + LLM reranking, not pure vector RAG. That shape fits the prose/guidance

slice of the corpus (Well-Architected text, architecture write-ups, READMEs) well; it's not a substitute for a structured DB on the numeric spec slice (pricing, exact hardware specs), which needs hard-constraint filtering. Claude Code/Codex/OpenCode-style agentic file search deliberately skips pre-built embeddings in

favor of live grep/glob exploration, because code needs exact identifier matches over fuzzy similarity and

indexes go stale fast the same logic applies to the Terraform/YAML/JSON config files inside the infra repos.

Agent memory systems (MemGPT/Letta-style) solve a different problem an agent's own experience

across interactions, not a shared reference corpus and map onto the feedback loop (constitution point 5), not the infra database itself.

-----

Concrete architecture: Git-native sync webhook or scheduled pull per source repo, diffed against the last-synced commit SHA,

reprocessing only changed files. Every extracted record carries its source commit SHA, giving point-in-time reproducibility for past recommendations.

Structured extraction parse machine-readable files (HCL, YAML, JSON, pricing dumps) into a proper

schema in a structured DB. Ground truth for anything scored numerically.

Hybrid text search (qmd-style: BM25 rerank) scoped to prose/guidance content only.

+ vector +

Agentic live exploration fallback for unrecognized formats or one-off deep dives; slower, not the default

path.

Separate outcomes/memory store recommendation => real-world result, feeding the SRE/DORA/FinOps

loop from the constitution. Different data, different retention policy, different store than (1)-(3). Does a constantly-updating source repo mean constant re-embedding? Naively yes, but not at full-corpus

scale if built correctly: Chunk-level content hashing. Hash each chunk (not each file) and skip re-embedding any chunk whose hash is unchanged a commit that touches one section of a doc shouldn't force re-embedding the whole

file, and a commit that touches an unrelated file shouldn't touch the index at all. This is what makes step 1's

diff-based sync actually cheap.

The vector layer and the keyword layer don't share a cost profile. BM25/keyword index updates are nearfree (term-frequency bookkeeping); vector embedding is the expensive step. That asymmetry is an argument for leaning on the hybrid design rather than a vector-only one: BM25 can stay current in near-real-time while the vector layer is refreshed on a batched or tiered cadence without the corpus ever feeling fully stale. Tier sync cadence by volatility and decision-impact, not uniformly. Pricing tables change often and matter a lot for cost scoring sync those fast. Conceptual guidance docs change rarely batch those on a slower

cycle. Local, on-device embedding (as runs) changes the economics too re-embedding cost is compute

time, not per-call API spend, which makes frequent incremental re-embeds far cheaper than they'd be against a hosted embedding API.

Treat embedding-model upgrades heavy event. [and |'s docs flag this directly:

as a separate, rare, own vectors aren't cross-compatible across embedding models, so switching models forces a full re-index. That's

a planned, infrequent migration, distinct from routine content-driven incremental updates budget for it

separately rather than triggering it accidentally.

7. Memory & context-handling systems four roles, not one choice

RAG (gmd), agentic file search, RLM, autonomous experiment loops, and reflective prompt evolution aren't competing answers to the same question each is the right fit for a different role. Treating this as “pick one

memory system" is the mistake to avoid.

-----

Role Best-fit approach Why qgmd-style hybrid BM25 + vector + Unchanged retrieval is the right model

Corpus retrieval P

rerank for prose; structured DB for when the answer lives in a few identifiable

(Section 5's problem)

specs chunks.

Reasoning over

context too large to retrieve cleanly

codebase analysis RLM (Recursive Language Models)

(1a/1b), or crosscorpus synthesis like [PrimeIntellect-ai/prime-agent],

"compare every arXiv:2512.24601

compute option across every provider for this

### workload"

Treats the full context as a variable ina

persistent REPL that the model examines, decomposes, and recursively calls itself over,

instead of chunking and retrieving. Preserves

the concept inside global structure retrieval loses.

Benchmarked: ~100x beyond a normal context window, beats compaction by 26%, CodeAct-with-subcalls by 130%, and Claude

Code's own context handling by 13%, at comparable cost.

Thelpi-

Numeric calibration

autoresearch |[karpathy/autoresearch| Fixed-budget experiments, one comparable (constitution

Lo point 5's

pattern + Command Code-style metric, MAD-based confidence scoring ( feedback loop)

implicit capture

Evolving vingthe the

GEPA (via DSPy) the guardrail

+

estimation logic

pattern from NousResearch/hermes-agentitself, not just the

self-evolution

#### numbers

The connective tissue: RLM and GEPA share a research lineage

paper and created DSPy, and RLM now ships as a DSPy module. Roles 2 and 4 framework rather than stitched-together tools. [PrimeIntellect-ai/prime-agent|'s "Continual Harness" is the right persistence architecture tying Roles 3 and 4 together: durable state kept separate from

base prompt, refined only through small evidence-backed updates, with rollback via snapshots. Its explicit caution is worth carrying forward unchanged: a passed quality gate only doesn't imply the estimate was actually correct.

GEPA reads rich qualitative feedback why

an estimate was wrong, not just by how much

and evolves the actual prompts/reasoning

strategy through reflective, sample-efficient search, rather than scalar-reward RL. Hermes's concrete version a is worth copying

directly: phased targets (skills > tool descriptions > system prompt code), and

every evolved variant must pass a full test suite, size limits, semantic-preservation checks, and human PR review nothing

auto-commits.

Omar Khattab co-authored the RLM

can run on one coherent

an immutable

proves what that gate checks it

-----

Bottom line: not a single memory system, and not really one "hybrid" either four roles, each with a best-fit tool, sharing two underlying frameworks (DSPy for reasoning-over-context and logic-evolution; a harness pattern for calibration-and-evolution persistence).

Which roles actually face the re-embedding/freshness problem? Only Role 1. RLM (Role 2 reads context live at query time rather than pre-indexing, so it has no standing index to go stale the trade-off is a larger

per-query compute cost instead of an indexing cost amortized over many queries. The calibration loop (Role 3 and GEPA/Hermes evolution (Role 4 both trigger on accumulated feedback or a schedule, not on sourcerepo commits, so a GitHub push to an infra repo doesn't touch either. The Continual Harness updates only

through explicit, evidence-backed [/refine] calls, automatically per-commit. Freshness discipline only

never

needs to be engineered once, for Role 1.

###### 8. Frontend | Ul surfaces

One engine, several entry points matching the multi-role backend rather than a single monolithic app:

CLI/ IDE-agent integration (primary, daily-driver surface) a slash command ([/infra-review], [/estimate])

inside Claude Code/Cursor/Codex-style environments, or a standalone CLI. This is where the target users

(from Section O's roles) already work, and mirrors the surface pattern of every tool compared in Section 1b/7 (Command Code, pi-autoresearch, Codex). GitOps-native trigger a GitHub App responding to a PR comment or auto-triggering on PR open, posting a

structured comment with the recommendation, confidence tier, and trade-off summary. Same UX shape as

Bugbot/CodeRabbit/Claude Code's managed review slots into an existing review habit instead of requiring

anew one.

Web dashboard for what a PR comment can't show well: the ATAM-style trade-off matrix, estimate-vsactual accuracy history (the calibration own performance, made visible rather than hidden), and the

infra database's commit-SHA provenance trail from Section 5. One conversational engine underneath all three the CLI, the PR comment, and the dashboard are

different front doors into the same reasoning process, not three separate tools, the same way Claude Code's

can be run interactively, triggered automatically, or dispatched to a background agent without being three different products.

Design rule for every surface: never show a bare number. Show the derivation trail which tier produced

the estimate, which pillars gated or scored it, what trade-offs got surfaced collapsed by default,

expandable on demand. This is the Cognitive Load lesson from Section 1b's DevEx material, applied to the Ul

layer rather than just the reasoning layer.

9. Open gaps not yet covered

A stock-taking pass, not a build-out. The engine (frameworks, estimation, storage, memory, evolution) and the

surfaces are covered; everything below sits around the engine and hasn't been designed yet.

-----

The write path. Everything so far ends at "here's the recommendation.” Nothing covers generating actual laC from it, PR-based apply workflows, approval gates before spend-affecting action, or drift detection/rerecommendation once something's live. (Now addressed in Section 10. Security of the tool itself. Prompt injection from untrusted repo/doc content is a real, unaddressed attack

surface. The micro-benchmarking sandboxes (1b) need actual security properties specified (network

isolation, resource caps, exfiltration prevention). Credential handling is undefined if the tool ever moves from advisory to provisioning.

Multi-tenancy vs. shared learning. The calibration loop and taste-sharing ideas both improve with crosscustomer data, but customer isolation was never resolved what's safe to learn/share in aggregate vs. what

must stay per-tenant. (Now addressed in Section 12. An evaluation harness for the tool itself. Live calibration (Section 7, Role 3 can't catch the tool getting worse after a GEPA evolution cycle before it reaches a customer that needs a held-out offline regression

suite in Cl, separate from live outcome tracking. (Now addressed in Section 11. The tool's own operating cost. FinOps (Section 2 covers the infra being recommended, not the cost of

running this tool RLM's per-query compute, GEPA/autoresearch-style evolution runs, autonomous loops

that can burn tokens by design. Needs the same budget governance as everything else. Trust and adoption strategy. No shadow mode (recommend silently, compare against actual engineer choices before the tool's suggestions carry weight), no gradual autonomy ramp, no defined path from audit trail to compliance sign-off. Cold-start for a brand-new organization (distinct from a new codebase, which 1b already covers) collides

directly with the multi-tenancy question above. (Now addressed in Section 12. Explicit scope boundaries of the tool itself. "State your scope explicitly” was applied to individual estimates

(1b) but never to the tool as a whole does it touch networking/topology, or only infra selection given an

already-decided architecture?

Lighter-weight, worth a mention: liability/positioning if a recommendation turns out wrong (advisory-only framing not legal advice); vendor-neutrality governance if there are ever commercial relationships with the

providers being scored; integration breadth (incident tooling, interoperating with FinOps tools an org already

has rather than replacing them).

##### 10. The write path from recommendation to applied infrastructure

Generation

Templates first: a library of parameterized laC modules tagged against the same pillar taxonomy as the infra

database (Section 5 the engine picks a module and fills parameters for common cases. Freeform LLM

generation is reserved for novel compositions the template library doesn't cover, and gets the heaviest

verification of anything in this pipeline, since it's the highest-hallucination-risk output the tool produces.

Verification gates before any human sees it

The constitution's gating layer (point 2), applied to generated code specifically:

-----

Plan against real current state ([terraforn plan]/ OpenTofu / Pulumi preview) apply against stale

never a

assumption of what already exists. Policy-as-code via Open Policy Agent/Rego the same compliance gates from Section 1 (data residency,

encryption) encoded as machine-checked policy on every plan, not just applied once at recommendation

time. Production precedent: a Rego policy that warns above a $100/month cost increase and denies outright

above $1000/month, evaluated automatically. Cost estimation on the actual plan, via Infracost closes the loop between “recommended because costoptimal" and "the generated plan actually produces that cost."

Blast-radius analysis replace vs. update-in-place, resource count touched. Destructive or high-blastradius changes get flagged for mandatory human review regardless of confidence tier. Secrets hygiene as a hard invariant generated laC must never write secrets to outputs (they land in state

files in plaintext). Secrets go to a secrets manager during apply, retrieved at runtime a known failure mode,

encoded as a non-negotiable check rather than a style guideline.

Approval confidence tier x blast radius, not a single toggle

The Tier 1-4 confidence framework from Section 1b directly gates autonomy:

Low blast radius High blast radius | destructive

Tier 1 1(empirical, mpirical, high hig Eligible for auto-apply the tool ha:

! foray pply once once oothas

Human review required, always confidence) earned trust Tier 2-3 (reference-class | Human review required, expedited

Human review required

### analytical) escalation

Shadow mode recommend and

Any tier, day one Shadow mode

compare, no apply

Shadow mode (Section 9 is the literal starting state for every new deployment: PR opened with the diff, plan, and cost estimate, apply switched off entirely, building the calibration data needed before any tier earns

auto-apply rights.

##### Apply mechanism integrate, don't reinvent

The tool shouldn't own execution. It emits a properly-formed PR that existing laC-CD tooling (Atlantis,

Spacelift, HCP Terraform) already knows how to consume state locking, concurrent-apply prevention, and

credential handling are solved problems at that layer. Spacelift's "Intent" feature (natural-language-to-infra, still fully policy- and audit-gated) is a live production precedent that this exact pattern is viable today, not

speculative. Closing the loop the piece that makes Section 7 calibration actually work Deployed resources must be tagged with the recommendation ID that produced them. Without that correlation, there's no way to match real telemetry back to the estimate that generated it. This tagging step is

-----

what turns "a recommendation was made" into the (estimate, actual) pairs Role 3's calibration loop depends

on not a nice-to-have, a load-bearing part of the constitution's feedback loop.

##### Scenario-specific generation modes (Section 3's overlays, applied to the write path)

Migrations phased cutover (blue-green resource sets), not a single replace, consistent with the Strangler

Fig pattern.

Mergers state-adoption mode ([terraform Terraformer /[pulumi convert]) rather than assuming

a

greenfield creation.

Distributed systems dependency-ordered apply across coordinated modules, since one service's outputs

are often another's inputs.

laC engine choice

OpenTofu (Linux Foundation/CNCF-backed, MPL 2.0 is the philosophically consistent default over

Terraform's BSL-licensed original vendor-neutral at the laC-engine layer for the same reason the rest of this

system avoids cloud-provider lock-in. Pulumi support matters for orgs already standardized on it, since forcing alanguage switch is its own adoption barrier.

# 11. Evaluation harness catching regressions before they reach a

customer

##### The core design decision: hard-fail vs. soft-fail

Mirrors the constitution's own gate/score distinction (points 2 vs. 3). Compliance is a boolean invariant; sizing accuracy is a quality metric. Collapsing them into one "eval score” hides exactly the failure that matters most.

The golden dataset

Known-answer sizing cases

production telemetry, or

exact match,

Compliance-gate adversarial

100% of the time. Hard-fail,

Scenario-overlay cases refactor, DR, greenfield/brownfield) laC-generation correctness outputs, passes the policy-as-code gate, passes quality.

Retrieval quality cases to catch regressions after a re-embedding cycle or chunking change.

Adversarial/prompt-injection

in Section 9. The eval harness is how six distinct categories codebases with settled, high-confidence resource profiles (mature

reference-class benchmarks like TechEmpower). Soft-fail: statistical tolerance, not cases deliberately crafted non-compliant options that must be rejected

zero exceptions.

at least one fixture per Section 3 scenario (migration, merger, distributed system,

so overlay logic can't silently break unnoticed.

cases known invariants the generated output must satisfy (no secrets in

[validate]). Hard-fail on invariants, soft-fail on generation a query expected-source eval set (precision@k, recall@k, standard IR practice)

cases deliberately poisoned repo content, tied to the security gap flagged

a regression in injection-resistance gets caught before a customer's

-----

malicious or just-weird README does it instead. Where it comes from, and how it grows

Seed from synthetic cases and reference-class benchmarks. Then promote real (estimate, actual) pairs from Role 3's live calibration (Section 7 into the permanent golden set once they've matured past a confidence threshold the same outcome data feeds both the live loop and the offline suite, gated by a maturity check

before becoming a permanent fixture. Every found regression, in review or production, becomes a new permanent case — standard regression-testing discipline, and the one habit that determines whether the set is worth anything a year from now. Adversarial cases should be actively red-teamed, not just accumulated from whatever naturally shows up.

When it runs

Every GEPA-evolved candidate (Section 7, Role 4 must clear the full hard-fail subset at 100% and the soft-fail

subset above threshold before a human reviews the PR Hermes's own pipeline shape (generate eval data >

evaluate candidates constraint gates > PR), populated with infra-advisor-specific content. Separately, run the full suite on a schedule, independent of any code change a revised compliance framework, an updated

reference benchmark, or a provider pricing change can silently invalidate a previously-passing case with zero

changes on your side. The eval suite needs the same freshness discipline already established for the infra database.

Statistical rigor for the soft-fail side

Reuse MAD-based confidence scoring (Section 1b) rather than comparing a single run against a hard threshold the question is whether a score dropped by more than the noise floor, not

whether it dropped at all.

RLM feeds GEPA's reflection step, once history is large not a replacement for it

GEPA's reflection reads execution traces to propose better prompts; RLM and GEPA solve different problems (Section 7 draws the line RLM is inference-time large-context reasoning, GEPA is prompt/program

optimization from qualitative feedback), but they compose. Once the golden dataset and its accumulated

trace history grow past what fits cleanly in a reflection prompt, RLM should sit in front of GEPA's reflection

step, digesting the full accumulated eval history to surface cross-cutting failure patterns rather than GEPA

reflecting on a fixed recent slice. RLM augments GEPA's input pipeline at scale; it doesn't compete with it as

an optimizer. Semantic preservation as a Goodhart's-Law guard

A GEPA-evolved sizing prompt could technically improve its golden-set score by learning to game the metric rather than genuinely sizing better the "prefer hard-to-game signals" lesson from the DORA/SPACE

material (Section 1b), now applied to evaluating the tool's own evolution rather than its output. Check that an evolved candidate's reasoning, not just its score, hasn't drifted from the original purpose.

The harness earns the right to reach a human, it doesn’t replace them

-----

Same caution as the Continual Harness's own principle (Section 7): a passed gate proves only what that gate checks. Every evolved candidate still goes through PR review before it ships, regardless of score.

##### 12. Multi-tenancy and cold-start resolved together, not separately

Cold-start is bad because isolation is total. These two were flagged as colliding in Section 9 because they are

the same problem seen from two sides loosening isolation carefully in one specific way improves both at

once.

The resolving principle: not one rule for "raw data" three different risk profiles

Codebase, cost/outcome figures, and free-text correction data don't carry the same risk, and treating them uniformly overstates the case for two of the three. Codebase never pooled, either tier. Companies publish architecture descriptions in case studies,

essentially never raw source. A pooled snippet can reveal proprietary logic or an unreleased feature a company would never choose to disclose. Only the abstracted structural signature (language, framework, DB,

request pattern) crosses the tenant boundary. Cost/outcome figures poolable raw, with explicit opt-in. The apt analogy isn't a blog post, it's a

benchmarking consortium: companies routinely contribute real figures to a compensation- or SaaSbenchmarking service in exchange for real, non-abstracted aggregate access. This is a legitimate second tier,

richer than abstraction, sitting alongside it rather than replacing it. Two things still matter even with consent: a configurable disclosure delay (a tenant may be fine with trailing data but not live visibility into current

spend during a sensitive period), and a separate storage/access boundary from the rest of the system,

since consent doesn't reduce the blast radius of centralizing many real figures in one place. Free-text correction data data-hygiene problem, not a policy one. Natural language is genuinely hard

— a

to reliably scrub of accidental identifiers (a system name, an internal project codename) regardless of consent. Needs deliberate scrubbing before entering either tier the risk here is technical leakage, not

business sensitivity.

The mechanism: federated-style local calibration, two pooling tiers

Each tenant's Role 3 calibration loop (Section 7 runs entirely within their

to their own (estimate, actual) pairs, nothing stored elsewhere, by default. Tier A automatic, abstracted, consent overhead. Only

no

structural signature, not raw data) is contributed to a shared prior, gated by pattern class never surfaces until enough distinct tenants have contributed to it. Low friction, applies to

every tenant unless explicitly opted out, and doesn't need per-instance consent management since figures or identifiable content ever leave the tenant boundary. Tier opt-in, raw, richer. A tenant explicitly consents to contribute real cost/outcome figures to

benchmarking pool, in exchange for real (not abstracted) comparative benchmark

consortium model, not the blog-post model. Gated by explicit consent, own boundary full private access

a delta (a correction direction against a

a k-anonymity threshold a

no raw

a

access back the

a configurable disclosure delay, and a

-----

storage/access boundary separate from the rest of the system. Codebase content is never eligible for Tier B regardless of consent; free-text correction data must pass identifier-scrubbing before entering either tier.

Both tiers use the same voluntary, reversible, push/pull shape as Command Code's taste system (Section 1b/9), generalized from an individual developer's preferences to an org's calibration contributions.

What this does for cold-start

Inserts a new evidence tier into the Section 1b framework, between Tier 2 (public reference-class

benchmarks) and Tier 1 (a tenant's own live telemetry): Tier 1.5 pooled anonymized cross-tenant prior.

Stronger than public benchmarks (drawn from real customers making real infra choices on this tool), weaker

than a tenant's own live data. A brand-new org with zero history inherits the pooled prior for any structural

pattern that matches, instead of being stuck at Tier 3 guesses. The trade-off to state, not hide

A tenant that opts out of pooling gets full isolation and a permanently slower ramp no Tier 1.5, dependent

on Tier 2/3 until their own telemetry accumulates. Communicate this explicitly at onboarding, consistent with

the explainability principle running through Sections 8-11.

Governance layer Needs explicit account-level choice: "fully isolated" tier (neither A B) for regulated customers who

an a nor

need cross-tenant contribution regardless of cold-start cost, Tier A the pooled default, with

zero versus as

Tier B available as an explicit additional opt-in. The actual contract terms defining what's safe to aggregate

especially for Tier B— need real legal review; a governance decision, not a purely technical one. One layer finer: inside a single tenant

The same opt-in/scope mechanism should be configurable below the org level for organizations that maintain

internal information barriers between business units (regulated financial services especially). This also connects to Section 10's approval matrix confidence tier x blast radius was two dimensions; RBAC is a

natural third. A junior engineer and a senior SRE shouldn't necessarily have identical auto-apply rights for

the same tier/blast-radius combination.

##### 13. Provider discovery finding sources, not just syncing known ones

Section 5 assumed the source repos were already known, This section covers how they get found in the first

place, and how new providers get caught as they launch. The right primary signal: Certificate Transparency logs, not domain registration

Since 2018, every publicly-trusted TLS certificate is required to appear in public, append-only CT logs or

browsers reject it near-total coverage of anything meant to be live and reachable. CertStream already exposes this as a free, open-source, real-time WebSocket firehose of every certificate as it's issued (~300-

-----

500/minute on a quiet day) the same infrastructure phishing-detection and brand-protection tooling already runs in production, pointed at a different classification target. Domain registration (WHOIS/zone

files) is a weaker complementary signal: registering a domain doesn't mean going live; getting a cert issued

strongly correlates with "about to serve real traffic," which is the moment that actually matters.

Three complementary channels, not one CT-log firehose (fast, automated) catches "something went live" within minutes. The firehose is the just

whole internet, so it needs a funnel, described in full below. Existing curated meta-lists new infra providers want to be discovered and already self-submit to the

Terraform Registry, the CNCF Cloud Native Landscape, maintained "awesome-cloud"” GitHub lists. Lower effort than reinventing classification since someone else already curated it. Scheduled broad search catches what the other two miss: rebrands of existing domains, soft launches,

funding/launch press coverage uncorrelated with a fresh domain. The discovery funnel borrowed directly from anti-phishing/malware-research CT-log

##### techniques

This isn't just analogous to phishing detection it's structurally the same problem (classify a newly-seen

domain from limited signal, fast, at internet scale), and there's directly relevant academic grounding: a RAID

2022 paper ("Content-Agnostic Detection of Phishing Domains using Certificate Transparency and Passive DNS") builds classifiers from CT/passive-DNS metadata alone, before any content is crawled. That reorders

the funnel metadata-only filtering should come before content-based classification, not after:

Content-agnostic pre-filter (metadata only, no crawl). CT-log issuance patterns and passive-DNS features can meaningfully separate categories before touching a single page cheapest, fastest stage, run against

the full firehose.

Typosquatting/lookalike detection, repurposed as a negative filter. Edit-distance matching, homoglyph

detection, combosquatting patterns the standard brand-protection toolkit used here to exclude

domains impersonating known cloud providers ([aws-cloud-deploy.xyz]) from being misclassified as new legitimate ones, rather than to protect a brand. Bulk-issuance pattern analysis cuts both ways. Bulk registration of similar root domains across many

TLDs in a short window is a typosquatting red flag in the brand-protection literature. The inverse pattern

one domain rapidly issuing certs for many subdomains, or a wildcard cert is a strong positive signal here:

the CT-log signature of multi-tenant PaaS giving each customer subdomain ([\*.vercel.app }-style). Same

a a raw

signal, opposite read depending on which pattern matches. Passive DNS + ASN/hosting correlation. Malware research clusters domains by netblock/ASN to catch bulletproof hosting. Here it verifies legitimacy in the other direction a domain claiming to be a serious new

provider but sitting on generic shared hosting is a red flag; real infra providers usually run their own

infrastructure well-known datacenter ASNs.

or

JARM/JA3 TLS fingerprinting for deduplication. Clusters domains running the same backend/C2 software

in malware research; here it detects that a "new provider” is actually a reseller or white-label of an existing one rather than genuinely independent infrastructure.

-----

LLM content classification only reached by whatever survives stages 1-5, on the specific question "does this describe a compute/storage/deploy product.”

Cross-reference against MISP/STIX-TAXII threat-intel feeds both a negative filter (catch compromised

infrastructure masquerading as a legitimate provider) and, architecturally, the right standard to build the

discovery pipeline's own classification data on, rather than a bespoke format it's the same shape as Section

12's Tier pooled-anonymized sharing mechanism, already solved and standardized by A a field that's been

doing exactly this kind of federated indicator-sharing for years. Detection latency and trusted-onboarding latency are different numbers

A provider can be detected within the hour via CT logs. Going from “a domain matching cloud-provider

patterns just got a cert” to "safe to actually recommend" requires understanding real pricing, compliance posture, and reliability track record, which can't happen at the same speed. Apply the same confidence-tier

framework already built for codebase estimates (Section 1b) to newly-discovered providers: a freshly detected provider enters at low-confidence, monitor-only status, ineligible for recommendation until it accumulates enough verified evidence (structured pricing API, compliance certifications, real usage data) to

graduate. Same tiered-trust pattern used everywhere else in this design, applied one level up.

The security implication

A high-volume, low-human-oversight discovery pipeline needs anti-poisoning defenses nothing should get

a fake or malicious "cloud provider” into the scored database just by standing up a convincing site with a TLS

cert. The low-confidence monitor-only entry status is part of that defense, connecting directly to the

prompt-injection gap flagged in Section 9. A second, distinct discovery problem: new services from already-known providers

Everything above catches new companies. It won't catch AWS quietly shipping its 220th service that's not a

new-domain event, so CT logs are the wrong signal entirely. This needs its own channel: provider

changelog/"what's new" feeds, and the more structured, machine-readable version watching a provider's

own Terraform provider repo for new resource types appearing in a diff. Same git-native sync mechanism as Section 5, pointed at a different kind of change: a new resource block in that repo is a new software-layer

entity (Section 5's revised model) needing the same feature/price/lock-in comparison against its open-source

equivalents as everything else.

# 14. Composable open-source stacks out-of-scope boundary and

# write-path note

Bare-metal/datacenter self-hosting is explicitly out of scope (hardware procurement, TCO/CapEx modeling, customer operational-capability assessment) a deliberate scoping decision, not an oversight.

What is in scope, and properly integrated into Section 5's entity model rather than treated separately, is the

-----

far more common real-world pattern: renting commercial compute and running an open-source software layer on top of it (a Hetzner instance running Coolify, a bare EC2 box running self-managed Postgres).

One write-path implication worth keeping distinct from Section 10's cloud-laC default: provisioning the

software layer on already-rented compute (Coolify, k3s, self-managed Postgres) can follow the same laC-style pattern as everything else Ansible, Kubernetes manifests, standard config management since no capital

purchase is involved and the compute itself is already provisioned through the normal cloud write path. It's a

software deployment, not a hardware decision, so it doesn't need the always-advisory-only carve-out that

genuine hardware procurement would.

###### 15. The end-to-end search algorithm search space and order, step

# by step

Everything before this section built a component. Nothing laid out the literal algorithm that ties them

together. The search space isn't a flat list to rank it's a nested, compositional space, and the order of

resolution is what keeps it tractable instead of combinatorially explosive.

Stage 0 Workload decomposition (cheap, structural, always first Section 1a/1b) Input: the codebase.

Output: a list of functional needs (relational database, object storage, compute runtime, message queue,

observability typically 3-8 per workload), each with a rough capacity estimate and confidence tier, plus the

scenario classification from Section 3 (greenfield, migration, merger, distributed, refactor). Nothing in the infra database has been touched yet.

Stage Hard gating, applied globally, before any per-need search (constitution point 2

1—

Compliance/security/data-residency constraints prune the entire provider-and-region universe once, up

front not per functional need, since the same gate governs the whole recommendation. A universe of, in

principle, hundreds of providers collapses to a compliant handful before any real search work starts.

Rechecked at finer grain in Stage 2 too a specific service SKU can fail a certification the parent provider

generally holds, so gating isn't fully separable into one pass.

Stage 2 Per-functional-need candidate enumeration (Section 5's revised entity model) For each functional

need, enumerate candidates from the surviving providers: commercial-native offerings (bundled with their own provider's compute, per the coupling asymmetry) plus open-source implementations (each requiring a separate compute-host sub-choice from the surviving compute providers). Per need, realistically 10-30+ raw candidates before any filtering several native services crossed with several open-source

alternatives crossed with several viable hosts for each.

Stage 3 Cheap per-candidate filtering (Section 1b Tiers 2-3 only, not Tier 1 yet) Score every candidate using

reference-class benchmarks and analytical modeling deliberately imprecise, fast, cheap. Purpose is

narrowing, not deciding: each functional need's candidate list drops to a shortlist of roughly the top 3-5

before anything expensive gets spent. Same cheap-before-expensive funnel logic as Section 13's discovery

pipeline.

-----

Stage 4 Cross-functional composition search over the shortlists (the step most naturally skipped) Picking the top-scored option per functional need independently and concatenating them ignores real cross-cutting effects: co-location/latency (cross-cloud calls are slower and incur egress cost), committed-use discounts (same-provider concentration can unlock pricing that per-need optimization would never

|IAM/compatibility friction across providers. This searches combinations of the shortlists

since it's shortlist-size raised to the power of number-of-needs rather than the full raw space small number of candidate packages, typically 2-5 whole-stack combinations worth taking further.

see),

tractable now,

producing a

Stage 5 Expensive empirical validation, only on the survivors (Section 7b Tier 1, cost discipline from Section

9 Only now does real micro-benchmarking or live-telemetry cross-referencing happen and only against

the 2-5 surviving packages from Stage 4, never the original raw space. Expensive evaluation is reserved for what already survived every cheap filter the direct answer to the tool's-own-operating-cost concern

flagged in Section 9.

Stage 6 Full pillar scoring and trade-off surfacing (constitution point 4, ATAM) Each surviving package gets

a full score vector across every pillar, never collapsed into one number. If no package dominates on all pillars, every contending package gets surfaced with its trade-offs explicit rather than the tool silently choosing.

Stage 7 Scenario-overlay adjustment (Section 3 Whatever overlay applies from Stage 0's classification

reweights pillars or adds constraints here modifying final scoring, not candidate generation, so the search

space itself doesn't balloon per-scenario. Stage 8 Confidence-tier labeling and handoff to the write path (Section 70/71 The final recommendation

inherits the confidence tier of its weakest supporting component, not its strongest a package is only as

trustworthy as its least-validated piece then hands off to the write path, gated by the tier x blast-radius

approval matrix.
