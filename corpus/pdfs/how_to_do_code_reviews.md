---
source: pdfs
silo: pdfs
source_id: how to do code reviews
url: ""
created_at: "2026-09-21T07:13:03.637563+00:00"
ingested_at: "2026-09-21T09:18:16.697185+00:00"
tags: [pdf]
author: ""
content_hash: b39e518b6218b801778e2e5cd4b44fab8cf9521d1064b99e3f414da579d02706
---
> 9/6/26, 6:50 PM Mike Julian on X: "We ditched code review at @DuckbillHQ (mostly) About a month ago, we found ourselves...

# How To Do Code Reviews

9/6/26, 6:50 PM Mike Julian on X: "We ditched code review at @DuckbillHQ (mostly) About a month ago, we found ourselves with 60 open PRs for a

...

![](img_p1_1.png)

#### X < Post

Q Search

Mike

(@) Home Julian

##### @mikejulian

#### o Relevant people

Q Explore We ditched code review at @DuckbillHQ (mostly)

Julian & @mikejulian Notifications About a month ago, we found ourselves with 60 open PRs for a team of Helping Al-native

co

five. They had been accumulating for a few weeks and we all had the negotiate, manage, ¢ sudden realization looking at two days of just code review. and cloud contracts.

Chat we were

at @DuckbillHQ.

5:08 AM Sep 6, 2026 186.9K Views

4 Grok

#### LiveonX Osi Wiss [ a

992

## pu] History Relevant

View quotes > bone is hosting Do Profile SLOPCANNON LIVE

##### © Post your reply More

#### Mike Julian & @mikejulian 13h

I had been tossing around the idea for a while about having Al do all code

review and so | just asked the team: what if we just...didn't review the PRs? Q2 1h 19K na

Roemmele & Brian is host Science Fiction Radio 24/7

Moon Dev & hosting

is

##### For Beginners

Mike

##### Julian & @mikejulian 13h

AFC

##### We decided to do a couple things instead:

##### slap Chelsea again. Itis Switch to a risk-based system

..

Alex @

##### Improve our guardrails (unit and e2e testing, post-deploy otly, stricter

##### linting and type checking, etc) CRYPTO Q2 n2 Q 86 20K na

# Mike Show more

##### Julian & @mikejulian 13h

##### With a risk-based system, we agreed that if your change touched the public

API/MCP, auth, design system, non-additive database schema changes, or

#### skills, What’s happening

agent it needed a human review.

We then enforced that with shell script to add github label. Sports Trending

a a

Lewis Skelly

##### Os thi 17K na

Sports Trending

#### Mike Julian & @mikejulian - 13h Improving guardrails was pretty easy, just expensive in tokens and

#ARSVCFC

attention. Trending

CENTCOM We enabled nearly every rule in ruff/prettier/eslint/ty and we improved our unit test coverage to a floor of 85%. -

Sports Trending j= Q ih na James and Gusto

46 16K

Mike

Julian & @mikejulian 13h o Show

more

to

We took a pretty high-level approach to preferring instrument the customer-facing signals that indicate a bad time is about to happen (eg,

Terms «Privacy Cookies Ac

| ingestion, data processing, response times, auth). There's a few areas we | + | + |
|---|---|---|
| went deeper on as needed, of | More | ©2026X |

course. +

0 Q 30 ih 15K na

![](img_p1_2.png)

![](img_p1_3.png)

##### 200 people murder...

# Mike &

##### Julian @mikejulian 13h A

We also spent a bunch of time rewriting our agent skills to ensure we were giving our agents better instructions. We had a lot of cruft from 2025-era Al.

#### un Qn na

### Mike

##### Julian & @mikejulian 13h

We wrote evals for our skills then tested them to see which had been consumed by modern LLM knowledge. We ultimately deleted alot and then

1/6

-----

9/6/26, 6:50 PM

X

Mike Julian on X: "We ditched code review at @DuckbillHQ (mostly) About a month ago,

improved what remained. Q2 un Q 33 12K we found ourselves with 60 open PRs for a

...

#### Qa

OO Mike -

##### Home Julian & @mikejulian 13h of While we there, we found alot of markdown docs had been

were

Explore accumulating from doc-happy agents and leading to context poisoning

We're now centralizing our docs into a single docs folder and requiring

#### Notifications shell Q2 01 Q 35 11K na Chat

those be written by humans. Location gets enforced by another script.

Mike

#### Julian & @mikejulian 13h o

that

Grok The shell scripts is actually a fun bit: why use an Al for something can

be deterministic? We wrote a bunch of scripts that Cl runs to enforce

various

| pu] | History | things like the aforementioned docs. We also force any changes to agent skills / agents.md go into their own PR. |
|---|---|---|
| Do | Profile |  |

##### 1 01 Q 32 ili 10K na

More Mike

Julian & @mikejulian 13h o

Final results, before vs after:

PRs merged: 353 -> 684 (80/wk —> 154/wk, +94%

##### Merged within 1h: 28% —> 45%; within 24h: 76% — 80%

Human-reviewed PRs median merge time: 26h No human-review median merge time: th

# Os ili 9.6K na

#### CryptoNinjas &

##### @crypto_ninjas 6h A

That backlog sounds exhausting. How are you maintaining code quality without the traditional review process?

nu thi 1.6K na

200 people murder...

2/6

-----

9/6/26, 6:50 PM Mike Julian on X: "We ditched code review at @DuckbillHQ (mostly) About a month ago, we found ourselves with 60 open PRs for a

...

X

a

#### (@) Home

Q Explore

Notifications

#### (O Chat 4 Grok

| 1 | History |
|---|---|
| A | Profile |
| © | More |

-----

9/6/26, 6:50 PM Mike Julian on X: "We ditched code review at @DuckbillHQ (mostly) About a month ago, we found ourselves with 60 open PRs for a

...

X

a

#### (@) Home

Q Explore

Notifications

#### (O Chat 4 Grok

| 1 | History |
|---|---|
| A | Profile |
| © | More |

-----

9/6/26, 6:50 PM Mike Julian on X: "We ditched code review at @DuckbillHQ (mostly) About a month ago, we found ourselves with 60 open PRs for a

...

X

a

#### (@) Home

Q Explore

Notifications

#### (O Chat 4 Grok

| 1 | History |
|---|---|
| A | Profile |
| © | More |

-----

9/6/26, 6:50 PM Mike Julian on X: "We ditched code review at @DuckbillHQ (mostly) About a month ago, we found ourselves with 60 open PRs for a

...

X

a

#### (@) Home

Q Explore

Notifications

#### (O Chat 4 Grok

| 1 | History |
|---|---|
| A | Profile |
| © | More |
