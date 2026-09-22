---
source: pdfs
silo: pdfs
source_id: godbye opencode issues
url: ""
created_at: "2026-09-21T07:13:10.702277+00:00"
ingested_at: "2026-09-21T09:16:48.813995+00:00"
tags: [pdf]
author: ""
content_hash: 5de14c2128d36e0278b24a3964ac287bd2a12fd7fedc6d14f0bfc5b156f8d216
---
> :  9/2/26, 6:01 PM Goodbye Opencode, you're a sink for time and tokens.

# Godbye Opencode Issues

:

9/2/26, 6:01 PM Goodbye Opencode, you're a sink for time and tokens.

Skip to main content

Search Reddit Log In

eee r/opencode 4mo ago

## | mira_fijamente

Goodbye Opencode, you're a sink for time and tokens. I'm not casual Opencode I've been using it for long time, I've configured everything configurable, I've

a user. a

#### tried plugins, I've built them, I've used vanilla Opencode, etc. In fact, | currently work with my own setup using 1

container per session so agents can run freely. | say that to make it clear that | can confidently say there isn't a single layer of this program that's actually solid. To be clear: I'm talking about the Opencode program and its whole monorepo ecosystem, the TUI, the CLI, SERVE, the Web Ul, etc. I'm not talking about the "opencode zen" and "opencode go" service.

#### In the latest 1.3 versions, Opencode had what seemed like acceptable issues, meaning it wasn't that bad.

But 1.14.7 is a real mess. Every update fixes one thing and breaks 10 others. For anyone asking for something specific: as of the date of this post, there was the 1.14.48 release, which lasted 3

#### days, where all subagents had no permissions at all. The problem is that | had some secondary workflows running

in automatic loop mode, and when | noticed unusual token spending, more than 2x, it turned out many agents

were trying to use subagents and those subagents had no permissions, but they hallucinated the tools instead.

And those hallucinations are also Opencode's fault because it silently injects far too many prompts. So the main

#### agents would keep trying to subagent, and if | lucky, the agent would realize something and

use a was was wrong

try to the commands its This wasted time because | thought it fault, maybe strange

run on own. my was my some

configuration issue, until | decided to test a downgrade and that did in fact work.

One of the biggest problems with Opencode is that these errors happen silently, without you realizing they happened. The example | mentioned proves that, because another user could easily believe everything was fine,

since the LLM, despite the difficulties, was still able to complete the task, but under the hood your rules were not executed, the subagents that specifically there to do the job properly not actually used. So now

were were you

have a worse result at double the token cost, not because of the LLM but because of the software around it.

So this is the truth | learned from Opencode: "LLM intelligence covers up bad software" | can't even be bothered to file an issue because they have something like 5 thousand open issues, not

exaggerating, where if you're lucky, an auto-reply bot answers you.

For anyone telling me "Stay on one version," I'd really like them to tell me which one. Because it would be very naive to think I haven't considered that, but the problem is that Opencode pushes out like 2 to 3 releases per day. And let me say this: there hasn't been any period of Opencode, at least in the last few months, where | can say there truly stable version, because either it had other bugs it had bugs Ijust hadn't discovered yet. It isn't

was a or

#### even useful to fork a private version of Opencode because its code is so huge and messy that there's nowhere to

get a handle on it, neither as a human nor as an LLM, maybe as an LLM if you have 5 separate two-hundred-dollar Claude and Codex accounts. This project honestly shows that it started in a good direction because there are elements of the software in

#### version that | genuinely liked, but it feels like something with direction shape. It feels like of

now no or one

the clearest examples of Al-generated clutter right now. The amount of tokens Opencode is honestly striking because it pushes in bunch of random prompts

consumes a

that | doubt any contributor can explain with certainty how they're built.

-----

9/2/26, 6:01 PM Goodbye Opencode, you're sink for time and tokens. : rlopencode

a

Skip to main content

Search Reddit Log In the fact that it differs by model, by agent, by provider, etc. Even for custom agents it injects prompts aggressively,

and | have all builtin agents disabled. And this would not be so bad if you could actually do something about it, but you can't configure it, and it isn't documented either. That's when | realized that at least 30% of token spending, hallucinations, and low-quality results is not the

fault, and not my prompts’ fault, it's the software itself.

| don't use plugins, it's vanilla Opencode. | even wrapped it in a container so the agents can simply run

unrestricted. I'm not asking for anything unusual, and | don't consider myself demanding. I'm literally asking for the expected vanilla behavior, which | think is the bare minimum.

So why would I Harness Coding Agent that limits the models, does worse job, and costs me more tokens?

use a a

I think the problem with Opencode is that it tries to be too many things and does none of them well. I'm not going to waste more time and tokens on it.

Honestly, I've already wanted for a while to migrate to another coding agent, but | kept postponing it because it meant learning a different kind of configuration. Not anymore.

There alternatives to keep going with Opencode, and at least for now really don't think there is I

are too many any rational reason for me to recommend Opencode to anyone.

3

charles\_r1975 4mo ago

+

| literally just switched from windsurf Q and everything has been great. I'm also curious what alternatives you were looking at?

&

mira\_fijamente OP 4mo ago

+

As | had mentioned... SILENT errors.

Also, closed-source tools like Cursor, Windsurf, Claude Code, etc. are worse than OpenCode. At least

OpenCode gives you a bit control harness.

more over your

About another option, | still have not decided because | need to test. | have several

seen open-source

options Q that promise more than OpenCode.

Since “pi” gets mentioned lot, it looks promising, but | cannot for However, with 50 thousand

a say sure.

stars on GitHub and barely a few open issues, it looks promising.

15 replies v

more

&o

sod0 4mo ago

OpenCode is incredible compared to Windsurf or Cursor Q. This here is very much a poweruser complaining. He is not even complaining about the result just about the token usage to obtain them.

-----

9/2/26, 6:01 PM Goodbye Opencode, you're sink for time and tokens. : rlopencode

a

Skip to main content

Search Reddit Log In

![](img_p3_1.png)

2 more replies Vv

street-Preference-88 4mo ago

i'm curious, where are you switching to?

zuricho 4mo ago

Pi Q,maybe

end

9 more replies Vv

4 more replies Vv

GfxJG 4mo ago

+

| can't recognize any of the challenges you describe in my own workflow Opencode has, for me, been a

huge upgrade on both Claude Code and oh-my-pi. But you do you.

&

mira\_fijamente OP 4mo ago

Oh, sure: in case | had not made it clear, and in case it was not OBVIOUS! | barely described one bug from

a sieve of SILENT ERRORS.

By the way, Claude Code is among the worst. They literally had a bug that took them a long time to

acknowledge, where it just burned tokens like crazy, which seems even worse to me since Claude Code is

FROM THE SAME PROVIDER AS THE PLAN. It is like, “Oh sorry, we have been accidentally charging you more than we should for months, whoopsieeee.”

&

philip\_laureano 4mo ago

Meh. | forked it and used OpenCode itself to fix itself. This is 2026. Everyone can code and if you have at least

few decades of experience, fix this yourself if it's really that bad a you can one

&

mira\_fijamente OP 4mo ago

+

It's 2026: software now requires an LLM subscription just to repair itself before it can even function.

3 more replies Vv

@®

atx-cs 4mo ago

+

-----

:

9/2/26, 6:01 PM Goodbye Opencode, you're a sink for time and tokens.

Skip to main content

Search Reddit Log In

![](img_p4_1.png)

1 more reply v

![](img_p4_2.png)

24 more replies v

@

enterme2 4mo ago

+

1 have problem whatsoever with subagents Q. | clearly defined its permission in subagent header.

no my

![](img_p4_3.png)

6 more replies Vv

&

liltechnomancer 4mo ago

+

I've been a big fan of opencode but it randome will start maxxing CPU usage and slow to a crawl lately.

[CRAY

®

shaonline 4mo ago

+

That's usually due to a "broken" ripgrep call that keeps running.

![](img_p4_4.png)

2 more replies Vv

![](img_p4_5.png)

2 more replies Vv

SrMortron 4mo ago ok

![](img_p4_6.png)

4 more replies v

@

took

Any recommendations? | like a lot of the basic structure it provides (agents, subagents, slash commands, and

permissions) and the TUI in general, but | don't about the rest (MCP, etc).

care

I've into of their automatic prompt issues, and whole slew of bugs from major to just supremely

run some a

irritating... but despite four releases a day, most of the bugs are still sitting unfixed for ages. I've looked at Pi, but agents the fundamental building block I for workflow. | dont want a new

are use my

project building harness entirely... just something somewhere in between Opencode and Pi, | think.

my own

&

mira\_fijamente OP 4mo ago

+

If, honestly, most appealing thing about Opencode is its permission system with glob keys (which, by way,

doesn’t work well either Imao), I'm still looking too. If | find good workflow, I'll let you know.

-----

9/2/26, 6:01 PM Goodbye Opencode, you're sink for time and tokens. : rlopencode

a

Skip to main content

Search Reddit Log In

4 UseMoreBandwith 4mo ago

+

why don't you make bug reports on GH ?

&

mira\_fijamente OP 4mo ago

+

Naive.

1 did it several times, until | stopped doing it. They do not respond, no matter if the bug is severe. | do not know what criteria they use to evaluate whether a bug deserves their attention or not. | think it depends the “popularity of a bug”??? | do not know.

on

![](img_p5_1.png)

reply v

a:

codenoobie 4mo ago

+

I'm new to this so could be a basic question, but how are you doing the one container per session thing?

&

mira\_fijamente OP 4mo ago

+

If you're more specific with the question, I'll gladly answer :3

@®

roguefunction 4mo ago

+

Just use pi.dev LER

jo]

Deep\_Ad1959 4mo ago

the silent prompt injection plus opaque permission model is the exact pattern that kills almost every harness once you scale past one happy-path workflow. the moment subagents start hallucinating tools because their

permissions got silently revoked, you can't even tell whether the model is the problem or the framework is. the real fix isn't a different harness, it's transparent permission state at every call (what got auto-injected, what got stripped, who proposed it, who executed) and a way to inspect the full prompt without an http proxy hack. LLM intelligence really does cover up bad software, and the bill comes due in token spend and

silently degraded outputs that no test catches.

fwiw the ‘transparent permission state at every call’ bit is exactly what we wired into runner, every tool call surfaces what got auto-injected and what got stripped before it executes, with a per-action approval prompt

and each side effect instead of trusting harness, https://s4l.ai/r/9b4ascaf

50 you can see approve an opaque

]

Quetxolotle 4mo ago

+

1 just use pi and add features i need v:

-----

:

9/2/26, 6:01 PM Goodbye Opencode, you're a sink for time and tokens.

Search Reddit

UE

c\_saucyfox 4mo ago

+

Cya

Related posts

![](img_p6_1.png)

os

![](img_p6_2.png)

### & r/MobileLegendsGame 4mo ago

+

Love that our Uranus kept on annoying and making our enemies busy that we secured the Lord twice, farmed all jungles, and pushed all lanes. 32 upvotes 10 comments

![](img_p6_3.png)

![](img_p6_4.png)

![](img_p6_5.png)

r/limbuscompany 6mo ago

Spoiler My attempt to read why Meursault, Ryoshu, and Sinclair got these this walp

342 upvotes 78 comments

![](img_p6_6.png)

![](img_p6_7.png)

r/thelastspell 6mo ago

#### I finally cleared the 70th Apocalypse Glintpine.

58 upvotes 9 comments

r/limbuscompany 6mo ago

+

© Spoiler Limbus only player My impression of the five fingers (Canto 9 spoilers)

15 upvotes 32 comments

![](img_p6_8.png)

![](img_p6_9.png)

Mm r/opencode 12d ago

+

| Made OpenCode Way Better

60 upvotes 23 comments

-----

:

9/2/26, 6:01 PM Goodbye Opencode, you're a sink for time and tokens.

Search Reddit

243 upvotes 113 comments

r/opencode 3mo ago

+

An Honest Take on Opencode

41 upvotes 40 comments

r/opencode 15d ago

+

#### Is Opencode Go worth it?

+

54 upvotes 59 comments

x

r/GrapheneOS 6mo ago

+

Doubts about Aurora Store

7 upvotes 11 comments

I r/opencode Tmo ago

+

#### Thank you opencode

+

287 upvotes 67 comments

r/opencode 28d ago Is it just me, has OpenCode become noticeably recently?

or worse

1 upvote 12 comments

r/opencode 27d ago

#### Opencode Go

45 upvotes 95 comments

![](img_p7_1.png)

![](img_p7_2.png)

r/opencode 12d ago Opencode CEO on the DeepSeek Situation

1.5K upvotes 142 comments

![](img_p7_3.png)

©

![](img_p7_4.png)

6mo ago

The Collection Banner (concept).

40 upvotes 7 comments

-----

:

9/2/26, 6:01 PM Goodbye Opencode, you're a sink for time and tokens.

![](img_p8_1.png)

![](img_p8_2.png)

Search Reddit

611 upvotes 36 comments

![](img_p8_3.png)

![](img_p8_4.png)

r/opencode Tmo ago

+

#### opencode

330 upvotes 65 comments

r/opencode 2mo ago

# Opencode is genuinely just terrible

14 comments

r/opencode 3mo ago

+

#### Is opencode free limited? Is there a way around?

32 comments

r/opencode 2mo ago

+

#### Is opencode becoming worse?

32 upvotes 32 comments

r/opencode 17d ago

+

#### Is it me or opencode models are very slow now?

5 upvotes 9 comments

Mm 17d ago

##### Any alternative for opencode go now?

18 comments

r/opencode 3mo ago

+

#### Starting with OpenCode, any initial recommendations?

27 upvotes 19 comments

r/opencode Tmo ago

+

What's the most annoying part of your OpenCode setup? 9 upvotes - 8 comments

-----

9/2/26, 6:01 PM Goodbye Opencode, you're sink for time and tokens. : rlopencode

a

Q Search Reddit Log In

6 upvotes - 48 comments

r/opencode 12d ago

+

Do you think OpenCode will get an IDE?

5 upvotes 18 comments

VIEW POST IN

##### Francais

Portugués (Brasil)

See more VV

Home Popular News Explore Best of Reddit Best of Reddit in Portuguese Best of Reddit in German Reddit Rules Privacy Policy

User Agreement Accessibility Reddit, Inc. © 2026. All rights reserved.
