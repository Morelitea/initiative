# Changelog

All notable changes to Initiative will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **A marketplace of your own, and decoration packs to fill it.** The marketplace now has two halves: a community's, where admins install dashboards and apps, and yours, where you get things that belong to *you* across every community you are in. The first shelf is decoration packs. Three to start: **Tabletop**, whose badge is the twenty-sided die this app already throws when you finish a task; **Soundcheck**, for bands and anyone who books the room and plugs in; and **Observatory**, for labs, field stations and reading groups with a whiteboard. Banners and frames move — dice land on a natural 20, a meter jumps, a record turns, electrons go round — while badges hold still, because a badge is a mark of belonging and a row of them has to stay readable. Download a pack and its pieces land in your collection; Settings › Profile is where you see what you have, put the pieces on, and remove a pack — which also takes off anything from it you were wearing. Mix pieces from different packs however you like.

- **Names look after themselves.** A `#` link, a `[[ ]]` link and an `@` mention all pointed at the name a thing had when you typed it, so renaming a task left every document and comment saying the old one. They now show what it's called right now — everywhere, without anyone editing anything. If what you pointed at is deleted or was never shared with you, the reference keeps its words, greyed out and no longer a link.

- **`[[ ]]` makes what it can't find.** It reaches the tools your initiative has — projects, documents, queues, counter groups, calendars, dashboards — and offers to create one when nothing matches. `#` still reaches everything that exists. And `[[ ]]` now works in comments too, not just documents.

- **"What links here" stops under-reporting.** A document's backlinks were built only from `[[ ]]` links, so anything connected with `#` was missing from the list.

- **Badges: a chip in a document that keeps itself current.** Type `/` in a document and pick a task's status, assignee, due date or priority, a counter's value, or an event's date. The chip shows what that thing is doing right now — a task moved to Done turns green in every document that mentions it, without anyone editing them. Click one to open what it is about. A chip for something you cannot see falls back to the name it had when it was written, and claims nothing about its state.

- **Name a thing inside a document with `#`.** Typing `#` in a document opens the same picker a comment has, over everything in the initiative — a project, a task, a queue, a counter, a calendar event, a dashboard. Pick one and its name sits in the text as a link that opens it. Naming a kind first (`#task:`) narrows the list, `@` still names a person, and both work as you type. Standard documents only: a whiteboard and a spreadsheet hold shapes and cells rather than prose.

- **React to a comment with an emoji.** Every comment now carries a row of reaction chips and a small button to add one. A chip shows the emoji, how many people picked it, and who — click it to add yours or take it back. The picker opens on the eight suggestions everyone sees (❤️ 👍 👎 😄 🎉 😕 👀 🚀) with the full emoji set searchable underneath. Anyone who can reply to a thread can react to it, and the community home's recent-comments feed shows what each comment drew.

- **The author hears about reactions, in a digest.** Reactions arrive in flurries, so every channel collects them rather than repeating. The bell keeps one line per comment: the next reaction to the same comment joins the line already there — naming who reacted last, how many others joined them, and the emoji used — and moves it back to the top, until you have read it. Email and push wait until the burst has settled and then arrive as one summary. Taking a reaction back before the author has read the line removes it again. It has its own switch under Settings › Notifications — wanting to hear about mentions no longer means hearing about every thumbs-up.

- **Every tool can now turn its comments off.** A project, document, queue, counter group, calendar, or dashboard has a switch under Settings › Advanced that takes its comment thread off the page entirely. Comments stay on by default, and turning them off deletes nothing — the thread comes back whole when you turn them back on. Tasks keep their own comments either way: a task's thread belongs to the task, not to the project page it sits under.

- **Search finds people too.** A Members tab sits second, between what is in the community and what was said about it. It matches this community's members and only this community's members, by the name they picked — and by their real name where the community shows real names. A name typed nearly right still finds the person, so you do not have to read the roster to learn a colleague's spelling.

- **Search now finds everything in a community, and reads inside it.** ⌘K and a results page of its own reach projects, tasks, documents, queues, counters, calendars, dashboards, tags and comments — matching names, descriptions, and the words inside a document, whiteboard or spreadsheet. Results are ranked under Tools, Comments and Tags, show the line that matched, and open the thing they found. It answers before you finish a word, and when nothing matches it offers the closest titles rather than an empty page.

- **An AI assistant can now read comments, not just write them.** The MCP server could post a comment but had no way to read one back, so an assistant could add a note to a task and never see it — or the discussion already there — again. Two read tools now sit alongside it: the thread on a task (or any tool that carries comments) and a single comment by id. The guild-wide recent-activity feed and the @-mention picker's search stay off the tool surface. Nothing new is reachable — comment reads go through the same route, authentication and access rules as they do in the app.

- **The statuses an initiative uses can now be read in one request.** Status columns belong to a project, so anything working across a whole initiative had to ask project by project and stitch the answers together. There is now a single read that returns the distinct columns across the projects you can see, each carrying how many of those projects use it — enough for a picker to say a status covers three of your four projects rather than implying it covers them all.

- **People have a profile page now.** Open someone from the member list or from a search result and you get their picture, their handle, whether they have Initiative open right now, and when they joined. It lives at a link worth sharing — `/u/jordan1234`, your handle with its number run on the end — and it is public and the same page whoever opens it, because it belongs to the person rather than to any one community.

- **Set a status.** An emoji, a line about what you are up to, or both, under Settings › Profile — using the same picker the rest of the app uses. It shows on your profile.

- **Dress your profile up.** A profile can wear a banner, a frame around the picture and a row of up to six badges, each picked from what you have: your library starts with the set that ships with Initiative, and decoration packs add to it. There is a picker per slot, so you can mix pieces from different packs freely. Decorations are chosen, never uploaded, so wearing one costs your community none of its storage.

- **Your profile, previewed while you build it.** Settings › Profile opens on the card other people see — picture, frame, handle, badges, status, whether you are around — and it follows every pick before you save, so nothing on the page has to be imagined. Your frame now travels with you: the avatar in the sidebar wears it too, and the account menu has a My profile link to the page itself.

### Changed

- **User settings reorganised, and it opens on your profile.** Profile and Decorations were two tabs that each held half the answer to "how do I look" — one had the picture and the status, the other the banner and badges — while the sign-in details sat under Profile, where they are nobody else's business. Profile is now the whole face (picture, name, status, packs, decorations) and opens first; **Account** is the new tab for how you sign in. Timezone moved to Interface, next to the week start — it answers the same question about how dates read to you — and it still sits beside the reminder time under Notifications, where you need it in context. The AI tab no longer appears at all for someone with no connection to configure and no way to bring their own key.

- **Every settings tab is built from the same parts now.** Nine tabs written at different times had drifted into three kinds of heading, two card styles and Save buttons in four places. They share one section component: the same heading weight, the same spacing, and Save pinned to the foot of the section it saves. Notifications splits into the three things it was doing at once — push, the daily reminder, and what you hear about — and the three settings for finishing a task are read together instead of found one at a time.

- **Frames sit on the picture, not around it.** Every frame is now drawn to one aperture, so the artwork meets the edge of the picture exactly instead of floating a few pixels clear of it or covering the face. Vinyl in particular had been painting over the whole picture. Removing a pack is a red **Remove pack** button that asks first and says what it takes with it, and the packs list is now a searchable, compact list built for a collection that grows.
- **Notifications arrive when they happen.** The bell used to ask the server every thirty seconds whether anything had come in, which meant a mention could sit unseen for half a minute and every open tab kept asking all day whether anything had. It now holds an open connection and hears about a notification the moment it is written — and marking one read updates the badge on your other tabs and your phone as well. The connection carries no notification content, only the news that there is some; if it cannot be opened at all the old half-minute check quietly takes over, so nothing is ever lost to a proxy that refuses it.

- **Creating a task and editing one now lay the fields out the same way.** The two screens share the same set of fields but arranged them differently, and the order had stopped meaning anything — Assignees and Tags sat between the dates and the Repeat rule that is worked out from the due date. Both screens now use the same named sections in the same order — Tracking, Schedule, People & labels, Properties — with the create dialog collapsing all but the title and description. Start date, due date and Repeat finally sit together under Schedule.

- **The task editor stops repeating itself.** The title was on screen three times over — in the breadcrumb, as the heading, and in the Title box — with the heading and the box showing the same live value, so typing in one retitled the other. The status was on screen twice for the same reason. Above the first field sat two separate lines explaining that this is where you edit a task. The Title box is now the heading itself, the status is stated once by its own picker, and both explanatory lines are gone.

- **A task's editor ends in two buttons, not six.** Save, cancel, move to project, duplicate, archive and delete all sat in one row at the foot of the task editor, so the action you almost always want looked exactly like the ones you almost never do — and delete sat two buttons from save. Save and cancel keep their place; move, duplicate, archive and delete moved behind a single "…" menu at the end of the row, with delete set apart below a divider.

- **"Browse the marketplace" is out of the overflow menu.** Adding a ready-made dashboard is the same kind of answer as making one from scratch, but only one of the two was on the page — the other sat behind the "…" button, where someone who has never opened it never learns the shelf exists. It now sits next to the create button on the dashboards list, at every width, and beside "Create your first dashboard" in an initiative that has none yet.

- **Every picker in the app now searches the way search does.** Mentions, wikilinks, queue links and the template pickers each had their own lookup, built before search existed: substring matching, no ranking, and a fixed list of three kinds of thing. They all ask the search index now, which means every one of them ranks its answers, matches before you finish a word, and forgives a misspelling. It also means they reach everything — a comment can now name a queue, a counter, a calendar event or a dashboard, not just a task, document or project.

- **`#` in a comment offers everything in the initiative.** It used to need the kind up front — `#task:`, `#doc:`, `#project:` — and those were the only three. Typing `#` on its own now searches across every kind at once, and naming a kind still narrows it. Every mention already written keeps working.

- **A misspelled name finds its person in every people picker.** Guild search learned this last release; the initiative roster and the pickers behind an @mention had their own copy of the matching rules and did not. There is one set of rules now, so they all behave the same.

- **Archived work stays out of search results unless you ask for it.** It was mixed in with live work; a switch on the results page brings it back when you are looking for something you put away.


- **Toasts stay up only as long as they take to read.** Every notification held the screen for a fixed five seconds after Chester finished typing it — a long wait for "Saved", and a short one for a paragraph of error text. The wait is now worked out from the message itself: a moment to notice it, plus reading time for what it says. Warnings and errors are held longer, a toast with a button on it gets time to press it, and there is a ceiling so nothing camps on the screen.

- **The search page names the community it is searching, and every tab stays open.** The heading said only "Search"; it now says which community the results come from. Tabs with nothing behind them were greyed out, so you could not check an empty tab for yourself or return to one once a changed query filled it — every tab is now reachable and an empty one says nothing matched. Finding out which tabs to grey out cost two extra searches per query, which are gone with it.

- **Search moved into the sidebar.** The search button sat in the tab strip above the page, where it read as one more tab. It is now a search field under the community name in the sidebar, labelled with the community it searches and showing the ⌘K / Ctrl+K shortcut. The recents strip is now only recents, and disappears when there are none.

- **Comment threads now run the full width of the page.** They were squeezed into a half-width column on tasks and into a slide-out panel on documents, which wrapped almost every reply. A thread is a conversation, so it now gets its own full-width row underneath, in the same place on every kind of page. The document side panel is now just the AI summary.

- **Replies are easier to follow.** Each level of nesting draws its thread line in a different theme colour, so you can see how deep a reply sits even where the indentation stops.

- **One emoji picker, everywhere.** The picker used for a project's icon and the new reaction picker are the same component, searchable and in your language, and it ships with the app rather than fetching its emoji list from an outside service — so it works on an install with no internet access.

- **A community admin's sidebar now lists the initiatives they are in, not every initiative in the community.** An admin who runs a community of thirty initiatives had all thirty in their sidebar whether or not they had anything to do with them. The sidebar is now their own workspace. Their authority over the community is unchanged — they can still open any initiative in it — and Settings › Initiatives has a new "Project managers" column for staffing one, which is also how an admin brings an initiative into their own sidebar: tick yourself. Unticking someone leaves them in the initiative as an ordinary member. The collapsed "Community admins" list at the bottom of an initiative's own members page is gone with it.

- **Guilds are now communities.** The name was picked for gaming guilds, and the people using Initiative turned out to be running far more than that — clubs, teams, departments, whole organisations. Everything you see now says community: menus, settings, notifications, error messages, and the help site, in all four languages. Nothing about how it works has changed; only what it is called.

- **Community pages have moved from `/g/` to `/c/`.** A page inside a community now lives at `/c/{id}/…` instead of `/g/{id}/…`, the per-community sign-in link is `/community/{id}/login`, and the platform tab is Settings › Admin › Communities. Old links do not forward — bookmarks, saved links and any per-community sign-in link you handed out need replacing with the new address.

- **A new install's first community is now called "Primary Community".** It was still called "Primary Guild" — the one place the old word survived the rename. Existing communities are untouched; this only changes what a fresh install starts with.

- **Every tab in a project, document, queue, counter group, calendar, or dashboard's settings now has an address of its own.** Sharing, the advanced options, a project's filter presets and its task statuses were pieces of on-page state: you could send someone to the settings, but never to the part you meant, and the back button stepped out of the whole page rather than back to the tab you came from. Each is now a place — `…/settings/access`, `…/settings/task-statuses` — so it can be linked to, bookmarked, and returned to. The bar still looks and behaves like tabs. Old links carrying a `?tab=` selector land on the section they named, and a tab you may not open refuses a typed address rather than only being hidden from the bar.

- **Names and titles no longer accept `#` or `@`.** Both characters already say something in Initiative: `@` opens a mention, `#` points at a task, document or project inside a comment, and a handle is written `name#1234` — so a name holding one read as the syntax rather than as itself, and searching for it split the term at the `#`. Task and event titles, project, queue, counter, calendar, dashboard, tag, initiative and community names, and the real name on your profile now turn both down and say why. Document names are the exception, since a document is usually named after the file it came from. Anything saved before this keeps the name it has.

### Fixed

- **The community calendar shows its calendars, and offers to add one.** The app's own page went straight to a grid of events: the list of calendars behind it, and the only way to make another, were tucked inside a filter panel that starts shut — on a page whose one and only filter was that list. A "Calendars" picker now sits on the toolbar row, with every calendar in the community, a checkbox each, a link to its settings, and "New Calendar" at the foot of it. "New Calendar" also has a button of its own beside the picker, and switching a calendar off is now counted on the picker itself so a thinned-out month says why.

- **The Repeat field no longer tells you twice that a task does not repeat.** A summary line sat under the Repeat picker restating whatever the picker already showed, so every task that does not repeat said "Does not repeat" twice in a row. The summary now appears only when there is a real schedule to spell out — "Every 2 weeks on Monday" — and Repeat has lost the dashed box that made the least-used field on the form the heaviest thing on the page.

- **A task description with a code block no longer stretches its board card out of the column.** Code fences, tables, images and unbroken strings were rendered at whatever width they wanted, so one task with a snippet in its description pushed its card past the edge of the column and left the whole board scrolling sideways. Code now wraps, wide tables and images stay inside the card, and a long title breaks rather than pushing. The same containment applies everywhere a description is rendered, so the task detail page and the hover preview get it too — and code blocks and inline code now read as code, on a tinted, rounded background.

- **Renaming a spreadsheet sheet keeps what you type.** The tab's rename box re-selected the whole name after every keystroke, so each new character wiped out the one before it and the sheet ended up named after the last letter typed. The name is now selected once when the box opens, as intended, and typing behaves normally from there.

- **Open tabs no longer flicker when you switch community.** The recents bar lists tabs from every community you are in, but switching community threw its contents away and fetched them again, blanking the bar for a moment each time. It now stays put — there is nothing about it that a switch changes.

- **Document text no longer shows through the editor's toolbars.** The formatting bar at the top and the actions bar at the bottom stay in place while a document scrolls, but their background was barely tinted glass, so headings and paragraphs slid visibly underneath them and the buttons became hard to read. Both bars are now solid.

## [0.64.3] - 2026-08-30

- **Link to documentation for help not the github page.**

## [0.64.2] - 2026-08-29

### Added

- **Connecting an app can now end with "waiting on an owner".** Some services hand an organization's install to the people who own it, so a request from anybody else becomes an approval sitting with one of them. The page you land on after connecting used to have no way to say that, and picked the closest thing it had. It now says it plainly: nothing failed, nothing is set up yet, and connecting again is worth doing once an owner approves it.

### Fixed

- **A model your provider offers is no longer rejected as "not found".** Testing a connection to an OpenAI-compatible service — OpenRouter and the like — checked the model against a list that had been cut to the first fifty entries, and those services offer hundreds. So anything past the cut came back as a model that does not exist, even though it does and the connection worked. The picker was reading the same shortened list, which is why only the handful it showed ever passed. Both now see the whole catalogue, and when a list really is too long to fetch in full, a model missing from it is no longer treated as proof of anything. The same fix reaches Anthropic connections, whose model list arrived one short page at a time.

- **Widgets that draw an app's data work again.** An app describes what each of its endpoints hands back — a name and a type for every value, and whether it holds several — and a widget is bound to those names before it ever runs. 

- **Publishing an app no longer drops the link between one of its dropdowns and the field it depends on.** An app can say where a parameter's values come from — one of its own reads, so a repository field offers that account's repositories rather than a text box. Where such a list depends on an answer already given, like the labels in a particular repository, the app also says which earlier field supplies it. That last part was being discarded when the app was published, so a dependent list could only ever be fetched unfiltered. It is now carried through and checked on publish: both sides have to name parameters that really exist, and a source cannot ask for the value it is filling in.

- **Dashboards that come with an app now appear in the marketplace.** An app can ship dashboards of its own — arrangements of its widgets, published with it, so an operator adds one file and the boards come too. 
- **Opening a link straight into another guild no longer loads the guild you were last in first.** A fresh tab starts on the guild it remembers and takes the one in the address a moment later, and in that moment the page was already asking for its data — so a link to another guild's board or marketplace briefly filled in from the wrong one before correcting itself. The page now waits for the address to win.

## [0.64.1] - 2026-08-29

### Fixed

- **Upgrading to 0.64.0 no longer fails on a database that has guild icons or profile pictures in it.** The two migrations that move those images into their own tables locked each table down before moving the rows, and the migration's own write was then rejected by the very policies it had just installed — so the upgrade rolled back, over and over, on any real deployment. A fresh install has no images to move, which is why it was never seen before release. Both migrations now carry the pictures across first and lock the table down after; nothing else about the result changes, and no manual step is needed — upgrade again and it goes through.

## [0.64.0] - 2026-08-29

### Added

- **The guild home's table searches and sorts the whole guild.** A search box sits above it, and the **Name**, **Initiative** and **Last updated** headers now order it — most recently updated first until you say otherwise. Both reach the guild's whole set for that tool rather than the rows already on screen, so a search never answers "nothing" while the match sits on page 4, and both ride in the address, so a searched and sorted table is a link you can send. Every circle behaves the same way: projects, documents, queues, counters, calendars and dashboards all take the same search and the same three orders.

- **Moderators can suspend an account.** Suspension is a freeze, not a removal: the person keeps every guild membership, every share, and everything they have written, and reaches no guild until it is lifted — at which point the account is exactly as they left it. They can still sign in to their own profile, where they are told it happened and why, so the app never simply stops working with no explanation. To everyone else they stop appearing in member lists, pickers and search for as long as it lasts, though work they already did still says they did it. Guilds are not told that one of their members was suspended.

- **Moderators can change a username.** For a handle that breaches the terms of use, the way a profile picture can already be taken down. The number beside it is unchanged, the person is told, and they cannot change it back themselves. All three moderator actions — picture, username, suspension — are recorded on the audit board, and none of them needs a break-glass grant, because none of them touches a guild's content.

- **There is an audit board.** Platform staff who can read audits — support and above — get a new Audit tab in the admin tools, listing what was done to accounts, by whom, and when, newest first, filterable by account. It starts with profile-picture takedowns, the one moderator action that exists today. Entries are kept after the accounts they name are deleted, so the record of what was done outlives the person it was done to; a deleted account shows as its ID rather than a name. Nothing can edit or remove an entry, including the software itself. Each entry is also written to the server log as one line of JSON, so an operator who ships their logs somewhere gets the audit trail with it.

- **Every guild has a banner.** It heads the guild's front page — the guild's own name and description across it — and runs along the top of its card in the community directory. A guild admin uploads one picture from Settings → Guild → Pictures and it is cropped to 4:1 and resized for you, so there is nothing to prepare and no second file to make. A guild without artwork wears a **banner fill** instead, which starts as the app's default blue and can be any colour; without a picture the banner is a short band rather than a full header. **Banner text** is black or white — whichever reads better on the fill, chosen for you when you pick one, and yours to switch when a picture calls for the other, and it now carries a shadow of the opposite tone so the words survive the patch of a photograph that goes the wrong way.

  The banner also carries the size of the guild — how many members it has, and how many have it open right now — and its layout is the guild's to set from the same panel. **Banner text position** is centered or left, where left lines the name up with the page's own content. **Banner fade** ends the banner at an edge, or carries it past that edge and dissolves it into the page so the tool circles and the table sit over its tail — soft or strong. A strong fade is the default, so a banner reads as the top of the page rather than a strip laid on it; a guild that wants the hard edge back sets the fade to none. The tool circles follow the banner's text position: centered under centered copy, and against the same edge when it is left. They are the top edge of the tray the table sits in rather than marks laid on the banner — each circle rises out of it and melts back into it — so a tool's name is always printed on that tray and stays readable over artwork of any brightness.

- **A guild-wide app connection can be granted at the vendor instead of typed.** A guild admin connects it once for everybody: the settings panel opens the vendor's install page rather than a form, and what comes back is written in by the app itself.
- **Initiatives can invite the whole guild in, and guild home says how.** Each initiative now declares how members may join it, under Settings → Details → Joining: invite only (the default, and what every existing initiative keeps) or open to anyone in the guild. Anything that isn't invite-only is listed on the guild home page — its name, colour, description, and how many people are in it — where a member can join an open one in a click and land straight in its work. A member who isn't in any initiative yet no longer meets an empty guild: guild home explains what initiatives are, lists what they can join, and says plainly when there's nothing on offer and an admin has to add them. "Browse initiatives" in the sidebar leads to the same list whenever the guild has one. Joining grants the built-in member role — view-only to start — and sharing still decides each item inside; nothing that was private becomes visible.

  That section is now the guild's whole initiative list, and the separate "My Initiatives" page is gone: the ones you're in come first — each card naming your role there and counting the work inside it, tool by tool, with the title leading in — then the ones you can join. The whole section folds away from its heading, per guild, and guild admins create initiatives from a button in it. Old links to the initiatives page (including the sidebar's "Add initiative") land on the guild home, and one that asked for the create dialog still opens it.

- **An initiative can accept requests to join instead of only invitations.** Alongside invite-only and open-to-anyone, an initiative can now ask people to knock: it is listed on the guild home like an open one, but joining waits on a project manager. A member asks with an optional note, the initiative's managers are notified and see the queue with who asked, what they said, and how many times that person has been turned down here before, and approving or declining notifies them back. Approving grants the same view-only member role every other join path grants — nothing that was private becomes visible, and declining changes nothing about what they can see. Being declined is not a ban: they may ask again, and only one request can be open at a time.
- **An open initiative can take in everyone who joins the guild.** A guild admin can mark an open initiative **auto-join**, and from then on anyone arriving in the guild — by invite, from the community directory, or through single sign-on — lands in it already a member, instead of an empty guild they have to find their way out of. It applies to arrivals from that point on and never reaches back over people already in the guild. Only an open initiative can carry it, so it hands out nothing a new member could not have joined themselves a moment later; guild admins are left out, since they already reach every initiative. A guild listed in the community directory is told when it has nowhere for arrivals to land, and can fix it from there.
- **Guilds can list themselves in a community directory, and be joined without an invite.** "Join a community" sits under the add-a-guild button in the left rail. It opens the directory: the search box and the category shelves take over the app's sidebar, and the page beside them is a card per guild with its icon, description, tags, and member count. Both the search and the shelf are in the address, so a filtered directory is a link. A guild admin lists theirs from Settings → Guild, picking at least one category and certifying the guild holds no adult or illegal content — the certification is asked at that moment and nowhere else, so a guild that keeps to itself is never put the question. A guild with room for only one member is never listed. Unlisted guilds are unchanged.

  Whether a server has a directory at all is the platform owner's decision, under Settings → Platform → Community, and it starts off. While it is off there is nothing to browse, nobody can join a guild without an invite, and the listing control is absent from guild settings. Turning it off later hides the directory rather than un-listing anyone: switch it back on and the same guilds are there.
- **An app service can be granted the app directory from Settings → Platform → App services.** Alongside "Act as members", the form now offers "Find other apps", which lets a service ask where another app installed in the same guild answers. An automation service needs both. It could previously only be conferred outside the app.
- **The community directory says who is in a guild right now.** A card carries the number of members with that guild open, beside the number of members it has in all. It is a live reading rather than a stored one, so it follows people arriving and leaving, and a guild nobody is in at that moment simply says how many members it has.

### Changed

- **An initiative's tool tabs read in the same order as the guild home.** Projects, documents, queues, counters, calendars, dashboards — one order everywhere, so the tab you reach for sits where the guild's tool circles taught you to look. An initiative that opens on no particular tool now opens on projects.

- **Guild icons are uploaded, not embedded.** An icon used to travel inside every reply that named a guild, which made a list of guilds far heavier than the list. It is now uploaded once, cropped square and resized for you, and fetched on its own — so it is cached between pages instead of resent with each one, and any picture works as a source rather than only a small square one. Existing icons carry over; one that isn't a square raster image under the new limit is dropped, and that guild shows its lettered avatar until a new one is uploaded.

- **Profile pictures are uploaded, not embedded.** A picture used to travel inside every reply that named a person — every task in a list, every comment, every calendar entry — so someone assigned to thirty tasks sent theirs thirty times in one response. It is now uploaded once, cropped square and resized for you, and fetched on its own, so it is cached across the whole app instead of resent with each list. Any picture works as a source rather than only a small square one. Existing pictures carry over; one that isn't a square raster image under the new limit is dropped, and that person shows their initials until a new one is uploaded. A picture linked from a single sign-on account is unaffected.

- **A profile picture can be taken down.** Moderators and above can remove someone's picture from the platform admin tools, for pictures that breach the terms of use. It removes the picture and tells the person; it never replaces it with anything, and no one can set a picture on someone else's behalf.

- **Everyone has a username, and it is what people see.** A username is a name you pick plus a number — `foobar#1234` — with the number added for you and shown quietly beside the name, so nobody has to accept `foobar7` because `foobar` was taken. Existing accounts get their first initial and last name — `Lee Janzen` becomes `ljanzen` — or a made-up one if there is no name to use; anyone whose username was assigned rather than chosen picks their own the next time they sign in. Where someone has not entered a full name, their username is shown instead of their email address.

- **A guild decides whether it shows real names.** New setting under Settings → Guild: on by default, and full names are shown where people have entered one; off, and members appear by username. A guild listed in the community directory always shows usernames, is never asked the question, and the setting is absent from its settings. Searching for a member follows the same rule everywhere you can search for one — the member list, the assignee picker, the initiative roster and an @-mention alike: you can always search a username, and full names alongside them in a guild that shows names. Typing a whole username with its number finds exactly that person. Notifications always name people by username, wherever they were written, because you read them away from the guild they came from.

- **Email addresses are no longer sent to guilds at all.** An account belongs to the person, not to the guild they work in, so a member's address no longer appears in the member list, member management, the member export, calendar invitations, or anywhere else inside a guild — members are told apart by their username, which is unique. Pending invitations show the address they were sent to partly hidden. Your own address is unchanged on your account page, and platform administrators still see addresses in the platform tools.

- **A closed account keeps its username.** Deleting an account still erases the name, address and picture behind it, but the username stays so that work it touched still says who did it — and an account whose username was assigned rather than chosen gets a made-up one in its place. Everyone deleted this way used to collapse into a single "[Deleted User]"; they no longer do.

- **An account is only ever changed by the person it belongs to.** Changing a password or an email address is now something only the account holder can do — the database enforces it, rather than each screen remembering to. A guild admin also no longer creates accounts with a password they choose: getting someone into a guild is an invite, so the password is set by its owner and stays theirs. Nothing in the app used the removed control.

- **Guild admins no longer edit member accounts.** A guild admin could previously change a member's display name and password. An account spans every guild its owner belongs to, so it isn't a guild's to edit: a guild admin now manages who is in the guild — inviting, approving, removing — and the account itself stays with the person and the platform admins. Nothing in the app used the removed control.

- **Each initiative settings tab has its own address.** Members, Roles, Properties, Export, and Danger zone are now real pages rather than tabs that reset when you reload, so you can link or bookmark one directly and the back button steps through them. Existing links to initiative settings still open where they always did. A notification about someone asking to join now opens the queue itself instead of the initiative's front page.
- **The Guild calendar app holds many calendars, not one.** Its sidebar entry now opens on every calendar the guild shares, overlaid in one view, and **any member can add another** — one for holidays, one for a recurring meetup, one for each person. Whoever makes a calendar owns it and decides its sharing, which starts as everyone in the guild can read it. The Calendars dropdown hides the ones you're not following, for you alone. The calendar the app arrived with is unchanged and still opens at its own address; removing the app sends all of its calendars to the trash together, as it always has for the one.
- **Comments are written in Markdown.** A comment body now renders the formatting you type into it — bold and italics, headings, bulleted and numbered lists, quotes, tables, links, and inline or fenced code, which stays literal rather than being formatted. Line breaks still land where you put them, and mentions of people, tasks, documents, and projects work exactly as before, including alongside formatting. Bare links are turned into links automatically, so pasted URLs no longer need to be wrapped by hand. An image is named as a link to itself rather than drawn in the comment, so opening it stays your choice. Existing comments are unaffected unless they happen to contain Markdown, which now renders. Comment previews — the guild home feed and a project's activity sidebar — render the same way, and they show mentions properly for the first time.
- **A long comment in the guild home's Recent comments can be read in place.** The feed shows the first two lines of each comment; one that runs longer now offers "Read more" beneath it, and "Show less" folds it back. Only comments that actually overflow get the control, and it re-checks as the column changes width. Mentions in the feed render as labels rather than links, so the whole entry stays a single click through to the comment.
- **The Cancel button sits beside Save when editing or replying to a comment.** It used to hang below the composer, away from the button it belongs with. Escape now backs out of an edit or reply too (once, if the mention list is open).
- **The Apps shelf only lists apps your server actually runs.** An app is served by a program the person running your server sets up — so a listing for one that they haven't set up yet, or have switched off, offered something that would install into nothing. Those listings now stay off the marketplace until the app is running, and adding one by hand is refused the same way. Dashboards are unaffected, and nothing changes for an app a guild has already installed.

### Fixed

- **A colour picker opened on red when the colour was black.** Black reads as no colour at all to the picker, so opening one on it showed red and could write that back over the colour you had. Black is now a colour like any other, wherever a colour is picked — tags, task statuses, initiatives, calendars, queue items, property options and the guild banner's fill.

- **Real names no longer appeared in a guild that shows usernames.** The rule reached the member lists and pickers but not the surfaces that carry a person alongside something else — a task's assignees, a comment's author, the latest comments on the guild front page, a project's activity, calendar attendees, queue rows, custom `user_reference` properties, dashboard filters and the data a custom widget is handed. All of them now name people the same way the rest of the guild does, including the cross-guild "my" lists, where each guild answers for its own rows. A comment also carried its author's email address, which no guild ever needed.

- **A guild admin could not turn "show real names" on or off.** Saving the setting failed outright. It is now on by default, so guilds keep showing names as before; a guild listed in the community directory still shows usernames and no longer offers the control at all.

- **Your username was missing from your own account page.** It sits under your email address now, shown but not editable, the same way your address is.

- **Rejoining a shared document no longer shows — or spreads — an outdated copy.** Coming back to a spreadsheet or whiteboard someone else kept editing could show the document as it stood when you left, until a page refresh; on spreadsheets, the outdated copy could even be pushed back into the live session and roll back the other person's work. Spreadsheets now wait for the live session's state before adopting any locally held copy, and whiteboards no longer treat another user's incoming edits as their own unsaved work — while correctly recognizing a live session when deciding whether local unsaved work should still win.
- **Dashboards that come with an app reach the marketplace.** An app whose listing bundles ready-made dashboards published them and then retired them again in the same pass, so they never appeared in a guild's dashboard picker. Both the shipped catalog and one an administrator adds now account for the dashboards each app declares. A dashboard an app stops shipping is still withdrawn, as before.
- **Editing an app service keeps the powers the form does not show.** The settings form rebuilt an app service's full list of granted powers from the controls it displayed, so saving an edit to an unrelated field — a base URL, an allowed origin — silently dropped anything else that had been granted. It now carries them through.
- **App and dashboard artwork now loads in the mobile app.** Marketplace listings whose artwork comes from the app registry — and the icons those apps show in the sidebar — were addressed as a path on the server, which the mobile app resolved inside its own bundle and drew as a broken image. They are now fetched from the server the app is signed in to.

## [0.63.4] - 2026-08-26

### Changed

- Adjusted the style of the personal space page headers.
- **Tab bars are consistent and fill their container.** The tab bars across the app — an initiative's tools, settings and admin sections, a tag's content, the sidebar's Initiatives/Tags switch, the document side panel, and the tabbed dialogs — were each sized differently: some hugged their labels, some stopped at a fixed width. They now share one component that spans the full width of whatever holds them, keeps each tab sized to its label, and scrolls sideways once the labels stop fitting. The view switchers on tool lists (table, board, grid, calendar) are unchanged — they stay sized to their icons inside the toolbar.

## [0.63.3] - 2026-08-26

### Added

- **Projects have saved filter presets, and a task view can be linked.** Every project now starts with four presets — All, Incomplete, Unassigned, and Mine — at the top of the task filters, and picking one puts it in the address bar, so a link shows a teammate the same tasks it showed you. The view (table, board, calendar) is linkable the same way. Edit the filters of a preset you are showing and it says so; "Reset to preset" puts them back. Project managers, the project's owner, and guild admins can save the filters currently on screen as a new preset for everyone, fold changes back into an existing one, rename or reorder them, and set which preset and which view the project opens on, under the project's Views settings. Everyone else picks from them and keeps their own filters as before.
- **Tasks can be filtered by whether anyone is on them.** The assignee filter gains "Assigned to me" and "Unassigned" alongside the people in it. Neither names a user — the server works out who is asking, and who nobody is — so a filter built on them means the same thing for whoever opens the link. Dashboard widgets can filter on unassigned work too.
- **The status filter can ask by category as well as by name.** Under the project's own statuses, the same dropdown now offers Backlog / To do / In progress / Done. Those ask about the *kind* of column rather than a named one, so a preset built on them keeps meaning the same thing in a project whose columns are named differently. Picking from both halves widens the list rather than contradicting itself.

### Changed

- **Due-date filters now apply everywhere the list does.** Filtering by overdue or due-soon was applied only to the visible list, so the board's per-column counts, the "archive done tasks" count, and CSV exports all quietly ignored it. The filter is now applied when the tasks are fetched, so everything agrees. "Overdue" now means due before today rather than before this exact moment.
- Adjusted background colors to reduce banding in Chrome based browsers.
- **A full guild no longer hands out invites.** When a guild has as many members as its user limit allows, the invite it would mint could only fail when someone tried to redeem it. Creating one is now refused, and both places an admin makes an invite — the guild's context menu and Settings → Users — say the guild is full instead of offering the action.

### Fixed

- **Several filter dropdowns had no name for screen readers.** The assignee, status and tag filters each sat beside a label that pointed at nothing, so all three were announced unnamed. They are now properly labelled, on project tasks and everywhere else those pickers are used.
- **The project page prefetched the wrong task list.** Opening a project prefetched tasks with filters that had drifted from the ones the page actually applies — it dropped tag and property filters and encoded the rest differently — so the prefetched result was never used and the list was always fetched a second time. Both now ask the same question.
- **Deleting a task drops you back in its project.** Confirming a delete on a task's page sent you out to the initiative's projects list, away from the sibling tasks you were working through. It now returns to the project the task was in.
- **Holding a guild on a phone opens its menu again.** Press-and-hold on a guild in the left rail was being taken as the start of a drag, so the guild menu — invite members, guild settings, leave guild — could not be reached by touch at all. Holding now opens the menu, and reordering has its own way in: pick "Reorder guilds" from that menu, or tap Reorder in the expanded guild list. While reordering, guilds can be dragged with a finger and a tap moves a guild instead of switching to it, until you tap Done. Reordering with a mouse is unchanged.

## [0.63.2] - 2026-08-25

### Added

- **Task and document tables remember how you left them.** The column you sorted by, the grouping you chose, and the columns you showed or hid now come back on your next visit — on a project's task list (kept per project, so one project's arrangement doesn't follow you into the next), My Tasks and Created Tasks, a tag's task list, and the documents list. My Tasks also stops claiming it is sorted by date window when your saved sort says otherwise. Settings and admin tables are unchanged: they are places you pass through, not arrange.
- **Documents and templates are listed separately, and the list filters by type.** An initiative's Documents tab now opens on a Documents / Templates toggle carrying each state's total, the way the projects list splits its own templates out; the templates view is linkable and answers the back button, and a tag's document browse lists documents only. The filter panel gains a document-type filter, so a list can be narrowed to text documents, files, whiteboards, spreadsheets or smart links; it counts toward the filter button's badge and Clear all.
- **An app being installed is an event.** A guild's installed apps now emit on the event bus like any other change — a webhook subscription can name `apps.created`, `apps.updated` and `apps.deleted`, and hear an install appear, its configuration state move, or it go away.

### Changed

- **Installed apps keep themselves up to date.** When a publisher releases a new version, your guild's install now moves to it on its own, so a fix arrives without anyone having to notice it exists. A guild that would rather read each version first can turn that off per app under Settings → Apps and update by hand from the same place — the button there names the version it will apply, and says "Up to date" when there is none. Apps you already have start out keeping themselves current. A version this server is too old to run is never applied, and neither is anything from a listing its publisher has withdrawn.

## [0.63.1] - 2026-08-23

### Fixed

- **Updating to 0.63.0 could stop partway with a database error.** The migration that gave every kind of content one `created_by` field also renamed the foreign keys named after the old field — but a guild created recently never had those keys to begin with, so the update failed on `constraint "calendars_created_by_id_fkey" for table "calendars" does not exist` and the app would not start. The rename now skips what a guild's schema does not have. An install stopped by this can simply update again; nothing was left half-applied.
- **The tag browser on a phone spilled over the documents behind it.** Opening "Browse by tag" on a narrow screen drew the whole tag tree past the bottom of its panel and on top of the document cards. The panel now keeps its tags inside it and scrolls, and its chevron turns over when it opens.

## [0.63.0] - 2026-08-21

### Added

- **Every tool has a comment thread.** Comments — previously only on tasks and documents — now live on projects, queues, counter groups, calendars, and dashboards too, guild calendars included. Whoever can see a thing can read and join its discussion, replies and @mentions work everywhere, the guild's recent activity feed carries the new threads, and the thing's creator is notified when someone comments.

### Changed

- **Tool lists have one control row on a phone.** A project or document list used to stack the create button, the import menu, the view toggle, a "Show filters" header and a lone Select button into four separate rows before the first card — on a phone the list started below the fold. Those controls now share a single row that stays put as you scroll: what's shown on the left, then filters, the view toggle, and an overflow menu holding import and Select. The filter panel starts closed and opens from the button — in a sheet from the bottom on a phone, rather than pushing the list down — and that button carries a count so a narrowed list still says so while the panel is shut. A Clear all button sits in the panel at every screen size, inactive when there is nothing to clear. Every list works this way — projects, documents, queues, counters, calendars and dashboards, a project's task list, a tag's tasks, and the cross-guild My Tasks, My Projects, My Documents and My Calendar. The create button drops out on narrow screens, where the floating add button already does the same job. An initiative's header shrinks to its name and settings gear with the description, badges and counts one tap away under Details, and a project card no longer repeats the initiative name on every card of that initiative's own list.
- **Projects, documents, queues, counters, calendars and dashboards now live inside the initiative they belong to.** Their addresses say so — a project reads as its guild, its initiative, then the project — and so do the tasks, events and counters beneath them. Because a list can only ever be one initiative's, the "filter by initiative" dropdown is gone from every one of them; the initiative you are in is the one you picked. A tool's tab is part of the address too, so you can link someone straight to an initiative's documents, reload onto the same tab, and use the back button through them.
- **Links you already have keep working.** A notification, a mention, or a queue item's linked entity resolves to wherever that thing now lives. Bookmarks and pasted links from before this change do not — the old addresses are gone rather than forwarded.
- **One name for who made something.** Every kind of guild content now records its author in a single field, `created_by` — replacing `author_id` on comments, `uploaded_by_id` on file versions, `installed_by_id` on installed apps, `created_by_user_id` on webhook subscriptions, `created_by_id` everywhere it already existed, and `created_by_user_id` on guilds and invites. A document's `updated_by_id` is gone — nothing read it, and who last changed a document is already recorded with the change itself. API clients reading the old field names need updating.
- **A document is named by `name`, like every other tool.** The documents API said `title` where projects, queues, counter groups, calendars, and dashboards all say `name`. The field, the list sort key, the upload form field, the linked-document rows on queue items and calendar events, and the export envelope now all say `name`; a comment's document context is `document_name`. Exports written before the rename still import. API clients reading or writing the old field need updating.
- **Every widget says where its data comes from.** A line under the title names the source, what it's narrowed to, and how many rows came back; click it for every filter in plain words, the display options, and a refresh. Names only ever resolve to what *you* can see.
- **Widgets can be filtered.** Status, priority, assignee, tag, project, any of the four dates, archived state, and title, with an optional "any of these" group. Dates can be relative ("due in the next 30 days"), so a dashboard never goes stale on the date it was saved.
- **Configuring a widget previews it.** The dialog runs the real widget against your own data while you choose.
- **Any widget can be read as a table** — a control in its header swaps the picture for the numbers.
- **The widgets do much more.** Stat shows a trend and a sparkline; chart gained ordering, a category cap, horizontal bars, a target line and highlighting; table shows assignees, tags, checklist progress and comment counts, marks overdue rows and totals columns; progress draws a meter per project; heatmap labels months and can count by creation or due date.
- **Charts read more cleanly** — lighter marks, room between bars, and a tooltip that leads with the value.
- **Widgets speak your language.** Their column headings and empty states were always English; marketplace widgets can now ship translations too.
- **Guild admins can transfer ownership of anyone's content.** Guild settings → Users has a Transfer ownership action on every member, moving everything that person owns in the guild — projects, documents, queues, counter groups, calendars and dashboards — to a chosen admin in one step. It works for people who have left as well as people who are still around, since accounts get abandoned as often as they get closed. This is the only place ownership is moved by hand, and only guild admins can do it.
- **Leaving a guild no longer hands your work to someone else.** Removing a member, leaving, or having access revoked used to make every project manager an owner of that person's documents and projects, or stop the removal until each project had been reassigned. Now it simply ends their access: what they owned becomes unowned, and guild settings lists it under Unowned content for an admin to claim whenever they choose. Anything already orphaned appears there too.
- **You can be removed from a guild even if you're the only project manager of an initiative.** That used to block the removal outright. Being a guild's last admin still does, since a guild needs someone who can run it.
- **A thing now has one owner, or none.** Ownership was recorded twice for projects and could name several people at once for anything shared, because the old hand-off made every project manager an owner. It lives in one place now, names one person or nobody, and never moves on its own.
- **Templates and archived projects are a filter on the projects list, not a second row of tabs.** An initiative page stacked two tab bars — one for the tool, another for Active / Templates / Archive. Now a single control above the list switches between Active, Templates and Archived, each showing how many it holds, so you can see there are three templates without going looking for them. The address bar remembers the choice (`?status=archived` is linkable and answers the back button). All three states render as the real project list: the same cards with icon, initiative, tags and task progress, the same search, tag, favorite and sort filters, the grid/list toggle, and bulk select for sharing and export. A template card carries a Template badge, an archived one shows when it was archived, and a button on the card un-templates or unarchives it in place.

### Fixed

- **A table bound to a spreadsheet range showed nothing.** Its columns were built without keys, so every cell landed in the same place.
- **Project progress was counted from a partial list.** Widgets read a fixed number of tasks at a time, so a larger project reported the wrong percentage. It now comes from the server's totals, and a widget drawing a partial list says so.
- **A widget whose data you can't see no longer tells you to configure it.** That prompt was shown both to authors who hadn't finished and to viewers whose access didn't cover the data; a failed load now reads differently again.

## [0.62.8] - 2026-08-19

### Changed

- **Webhook events now always name something you can fetch.** A project's statuses, a document's file versions, an initiative's roles, and a change to who a project (or document, queue, counter group, calendar, or dashboard) is shared with used to arrive naming an id with no endpoint behind it. Each now arrives as an update to the thing it belongs to — `projects.updated` with `statuses`, `documents.updated` with `versions`, `initiatives.updated` with `roles`, `projects.updated` with `sharing` — the same way a task's tags have always been reported. Every id in an event resolves to a resource you can read back.
- Document reads accept `?include_content=false` to return everything except the body. A document's body is by far the largest thing the API returns and usually isn't what changed, so a subscription reacting to an edit no longer has to fetch it.
- **Gantt widgets are now a proper project timeline.** The chart draws a line on today's date, so you can see at a glance what is behind and what is still ahead. Rows fold: bind one to Projects and each project is a single bar you can open to reveal its tasks, and a bar's fill is how much of the work under it is finished — a project that is halfway through its tasks is a half-filled bar, with the count beside its name. Bound to Tasks, you can group rows by project, status, priority, or assignee instead, and a total row across the top sums up everything shown.

### Fixed

- **Leaving a guild works again.** If you belonged to any of the guild's initiatives, leaving it failed outright with a permission error, and so did stepping out of an initiative you managed. Both go through now, and the change is still reported to any webhook watching.
- **The overdue digest no longer counts tasks you have set aside.** It swept up tasks in archived projects, and tasks you had archived yourself, so people were chased about work they had already cleared off their plate. The daily email and push now count only live tasks in live projects, matching what My Tasks has always shown.

## [0.62.7] - 2026-08-18

### Added

- **An app's page now matches your theme.** An embedded app is told your light or dark mode and your colors — color theme and guild accent included — when it opens, and again the moment you switch, so it can recolor in place instead of staying bright white inside a dark Initiative. Apps pick this up as they add support; one that hasn't yet simply keeps its own colors.
- **Outbound webhooks (API-only for now).** Register a URL via the API and Initiative POSTs a signed notification when content changes, filterable by event type and field. A subscription only ever delivers what its creator can access.
- Comments, subtasks, queue items and counters can now be fetched individually by id, and any resource can be fetched after it's been deleted with `?include_deleted=true` while it's still in the trash.

### Fixed

- **Breadcrumbs are now consistent everywhere.** Every project, document, queue, counter group, calendar, and dashboard page — and each one's settings page — now shows the same trail back to its initiative. Settings pages had dropped the initiative from the trail, and a counter group's page had no breadcrumb at all; both now match the rest.
- **The overdue digest no longer counts tasks in template projects.** Templates hold blueprint tasks whose due dates were never real deadlines, so anyone with a dated template project got emails and push notifications about work that did not exist. Only tasks in real projects are counted now.

## [0.62.6] - 2026-08-14

### Added

- **Android notifications now arrive on channels you can tune individually.** Comments, calendar events, event reminders, access requests, and the new overdue summary each get their own entry in the system notification settings, so you can silence one kind without silencing the rest — previously only five kinds were sorted this way and everything else arrived under a general heading. This part needs the updated app; the notifications themselves reach existing installs either way.

### Changed

- **An app is told who you are without being told which account you are.** Apps now know each member by an identifier unique to that app's own installation, rather than by an account id shared across everything. Two apps cannot compare notes and work out they are dealing with the same person, and an app installed in two guilds cannot link those guilds to one of your members.
- **The task-assignment digest now waits for the flurry to end.** It used to send on the first assignment and then go quiet for an hour, so a single task got an instant email while a batch of twelve arrived as one message plus a long silence — the opposite of what a digest is for. It now sends once nothing new has arrived for five minutes, or after thirty minutes if assignments keep trickling in. A lone assignment still reaches you promptly; a burst arrives as one summary.
- **Assignment email and push are the same message on the same schedule.** Push fired once per task, so twelve assignments meant twelve buzzes while your inbox got one summary. Both channels now ship together from the digest, and a summary covering one task still opens straight to it. The in-app bell is unchanged and still lists each assignment as it happens.
- Turning off the assignment email no longer stops push as well — the two toggles are now independent, as the settings page always implied.

### Fixed

- **Overdue tasks now reach your phone, not just your inbox.** The daily overdue digest was email-only despite the push toggle sitting beside it in notification settings, so anyone relying on the app for reminders never heard about overdue work. It now sends on whichever channels you have on, and turning the email off no longer silences the push. Tapping it opens My Tasks, since the digest spans every guild you are in.
- Push notifications sent by the app's own background work — the overdue and assignment digests, and access-request notices — reached the device and then failed while recording the delivery, which could leave a stale device registration in place after the phone had been handed on.
- **Un-assigning someone before the digest goes out now withdraws the announcement.** Previously the email still told them they had been assigned a task they no longer held.
- Sent digest entries are now cleared a week after the fact. Nothing had ever deleted them, so every task assignment ever made left a permanent row behind.

### Fixed

- **An app's page opens wherever the app is, however you got there, however long you have been signed in.** An app placed in an initiative now loads its page instead of an empty frame. So does one reached by clicking through the sidebar rather than by opening its address directly, and one opened after a long-running tab has been sitting idle. The browser permission an embedded app needs is now settled by which app services the deployment has connected, so it no longer depends on which page a tab happened to load first or on how recently you signed in.

## [0.62.5] - 2026-08-14

### Added

- **You decide whether an app may act as you.** A guild admin installing an app puts it in the guild; whether it may make requests in your name is a separate question, and now yours to answer — reads only, or reads and writes. Withdrawing takes effect on the app's next request, and leaving the guild takes it with you. Guild admins can see who has allowed what and end any of it, including everyone's at once without uninstalling the app, but cannot allow it on somebody else's behalf.
- **Every app has settings of its own**, reached from the gear beside its name in the sidebar. It shows what you control: your own answer about the app acting as you, and your own half of any connection — plus, for guild admins, what the guild owns, being the shared credential, where the app appears, and what each member has given it.
- **An app acts only in the guilds that installed it.** A delegating app reaching a guild now needs that guild's install to be present and switched on, alongside the power its registration grants — so uninstalling an app, or turning the install off, ends what it can do there without touching any other guild.
- **An app is granted the power to act as your members individually.** Delegation follows the app's own registration — its keys, its grant, its switch — rather than one setting shared by the whole deployment. Turning an app's delegation off, or turning the app off, ends what it can do straight away.
- An app service registration can hold the public keys its app signs delegation tokens with, as a JWKS — pasted into the registration form or declared in the app services file alongside the app's other settings. Two entries in one key set is how an app rotates its signing key without downtime, and clearing the field removes it.

### Changed

- An app's embedded page is granted only the browser features its manifest asks for, from a fixed list — camera, microphone, location, screen capture, clipboard, and fullscreen. A surface that asks for nothing runs with all of them denied. What an app requests is part of what it declares, so it can be read before installing.
- **A guild tells its members about the guild, and its admins about running it.** Everyone in a guild still sees its name, description, icon, member count, and whether content is currently read-only. The administration details — the storage and member limits set for the guild and its trash retention window — now reach guild admins only, matching the settings pages that are already theirs alone.

### Fixed

- **Dashboards render on a deployed instance.** Widgets are evaluated by a WebAssembly runtime that the served content policy did not admit, so every widget on every dashboard failed with a runtime error. The runtime's own bundle is now served with a policy that admits it; the policy the rest of the app is served with is unchanged.
- An app whose service stops matching what this deployment registered now stops offering its embedded pages, not only its data — the two halves of an app go quiet together. Both return on the next successful verification, and the app reads as unavailable meanwhile instead of opening a surface that cannot load.

## [0.62.4] - 2026-08-13

### Fixed

- An app's embedded surface now fills the page instead of sitting in a short box at the top.

## [0.62.3] - 2026-08-13

### Added

- Apps can now appear inside an initiative as well as guild-wide. An app that offers an initiative surface gets a row in each initiative's sidebar section, opening a page scoped to that initiative — the same install, told which initiative it is being read in.
- App surfaces name who they are for: everyone in the guild, an initiative's managers, or guild admins. An entry only appears for a reader it is meant for.
- **Dashboards have a settings page.** A dashboard can now be renamed, described, tagged, shared, and deleted like every other tool, from a Settings button on the dashboard itself.

### Changed

- **Every tool's settings page is the same page now.** Projects, documents, queues, counter groups, calendars, and dashboards share one layout — Details, Access, Advanced — with rename and delete always in the same place. Calendars pick up the tabbed layout the others already had, and whatever is particular to a tool sits alongside the common settings rather than replacing them: a project's schedule and task statuses, a counter group's duplicate, a calendar's color, a document's copies.
- Deleting a tool now names the thing being deleted, so the confirmation reads "Delete "Q3 Roadmap"?" instead of naming only its kind.
- An app service can now be wired up with a separate browser address. Its base URL is where Initiative's own server calls the app, so it may be an address only your network resolves; the new browser address is where a member's browser loads that app's embedded surfaces and connection pages. Leave it blank — the default, and what every existing registration keeps — and one address serves both, exactly as before.
- Guild admins choose which initiatives an app appears in, from the app's own settings. New installs appear in every initiative, which is the default.
- **Dashboard widgets are set in the same type as the rest of the app.** A widget's headline number carries the weight the figures on My Stats do, and a number that reads as good, cautionary, or bad is the same green, yellow, or red wherever you meet it. Labels, captions, table headers, and chart axis ticks now sit at one legible size instead of shrinking a step per widget.

### Fixed

- An initiative that renamed its managing role, or gave a second role manager standing, now sees the manager affordances it should: the sidebar reads the role's manager flag rather than looking for the built-in role by name.
- Pinning follows the same rule: a manager of an initiative can pin and unpin its projects whatever their role is called.

## [0.62.2] - 2026-08-13

### Fixed

- **The marketplace no longer offers an app that was removed.** A listing that ships with Initiative is taken off the shelf when a release stops carrying it, instead of lingering in the catalog of every instance that ever saw it — which is why the automation app could appear twice. A guild that already installed one keeps it; it simply stops being offered.
- **A listing shows the version you would get, not a history.** One app, one current version. Which version an install is running, and updating it, stay in guild settings where the app lives.
- **Installed apps open again.** Clicking an app in the sidebar did nothing. An app with a page of its own now opens it — with a tab for each view where an app offers several — and an app that only needs an account connected opens that form where you clicked, rather than sending you to look for it in guild settings. Apps that just feed widgets into dashboards have no page to open, so they tuck under a “show more” instead of taking up a row. Each app is now shown with its own artwork.

### Changed

- **Everyone can see the app store now.** The Apps section shows for every member, not only guild admins. A member gets “Browse the app store” where an admin gets “Add an app” — the same shelf, where each listing is tagged if your guild already has it, and one it does not says to ask a guild admin for it. Adding an app is still an admin's to do.
- **The sidebar drops “All Projects” and “All Documents”.** Both are a keystroke away in the command palette, and the space now belongs to your guild's apps. The apps list also matches the initiatives list above it — the same expand control, and “Add an app” sits at the bottom where “Add initiative” does.
- **A guild's front page is now a browser for its tools.** It was a fixed dashboard of personal statistics and activity cards — the same figures My Stats already gives you, mixed with a few shortcuts. In their place is a row of the guild's tools across the top: pick one and everything of that kind in the guild is listed underneath, whichever initiative it lives in, alongside that initiative, its tags, and when it last changed. Only the tools your initiatives actually use get a circle, and the tool you're looking at is part of the address, so the view can be bookmarked and shared. Underneath the list, the guild's latest comments carry on as before — they stay put whichever tool you're browsing, and each one links to the task or document it was left on.
- **Focus settings on My Tasks are now a window per priority.** Instead of one date range for everything plus an "always include urgent and high" switch, each priority gets its own slider: how many days ahead the Focus list looks for that priority, from today-and-overdue only up to a month out, or "any date" to keep that priority on the list whatever its deadline. Existing settings carry over.

## [0.62.1] - 2026-08-13

### Fixed

- Migration 162 frozen key error prevented migration from completing on v0.62.0

## [0.62.0] - 2026-08-13

### Added

- **A platform administrator can create a guild for another account.** The named account becomes the guild's admin and owns its first initiative, and the administrator who created it is left holding nothing in it. Everyone else creates guilds for themselves as before.
- **Dashboards.** A new tool inside an initiative: a canvas of widgets you drag and resize, reading that initiative's own projects and tasks. Seven kinds of widget — a headline number, charts (line, bar, stacked, area, pie), a progress bar, a funnel, a heatmap, a table, and a timeline — each with its own options, and a live preview while you pick one. Dashboards are read-only by design: they show work, they never change it. Sharing works like every other tool, so a dashboard can be yours alone, shared with named people or roles, or open to the whole initiative.
- **Counter board dashboard in the marketplace.** A scoreboard for whatever the initiative is tallying: one counter as the headline, its progress toward the goal, and the rest of its group charted alongside. Install it, then point each widget at the counters you want.
- **Event planner dashboard in the marketplace.** The initiative's events laid out the way an organizer thinks: everything on a weekly timeline, with the full event list underneath. Installs in one step and needs no setup.
- **Team activity dashboard in the marketplace.** A ready-made pulse of the initiative's people: work by person, the daily rhythm of completions, the open pile by priority, and the finished total as the headline. Installs in one step and needs no setup.
- **Apps, and a marketplace to add them from.** The marketplace is a searchable shelf of ready-made dashboards you can install into an initiative in one step, and of apps that add something the whole guild shares rather than any one initiative. The first app is a guild calendar: an ordinary calendar that belongs to the guild, visible to every member from the moment it is added, with the same views, event editor and sharing as any other. Apps live above your initiatives in the sidebar and are managed under guild settings, where they can be renamed, turned off, or removed — removing one moves what it created to the trash rather than deleting it. Only guild admins can add or remove apps; a guild with none installed shows nothing to its members.
- **The marketplace shows examples using sample data.** A listing's preview draws sample rows, so you see the shape of what you would get without it reading anything from your guild.
- **The app platform.** An app can now be more than something the marketplace lists: it can be a service your operator connects, which contributes widgets to dashboards, pages inside Initiative, and events. Your operator registers an app once for the whole deployment; a guild admin installs it and fills in whatever it asks for, and where an app authorizes people individually — the way GitHub does — each member connects their own account, so nobody borrows anyone else's access. Admins can see who has connected, and revoke or block any of it. Removing an app, leaving a guild, or closing an account takes the credentials with it. Some apps are provided by the platform and appear in every guild; those cannot be removed, and they say so.

### Changed

- **Sign-in and server-connection redirects are now decided before a page renders.** Landing on an app page while signed out, signing out, or opening the mobile app before a server is set now hands you straight to the right screen instead of briefly mounting the app shell and bouncing out of it. The old approach depended on that shell tearing down at exactly the right moment — the failure behind the blank page in 0.61.0.

### Removed

- **The advanced tool is gone.** The optional embedded panel an administrator could point at a companion service — configured with `ADVANCED_TOOL_NAME` / `ADVANCED_TOOL_URL`, switched on per initiative, and listed as a tool inside one — has been removed, along with its list, sharing, tags, trash entries and role permissions. What Initiative stored for it was a name and a sharing record around content the connected service already owned, and those rows are deleted on upgrade; the service keeps everything it holds. A deployment that wants a companion surface connects it through the app platform instead, which is the general form of what those settings were a single-purpose version of. The `ADVANCED_TOOL_*` settings are now ignored and can be dropped from your configuration.
- **The pre-0.53.5 copies of guild data in the shared database schema are gone.** Installs that predate 0.53.5 kept a frozen second copy of every project, task, document and so on from before guilds moved into their own database schemas. Nothing has read or written it since; upgrading now drops it. Guild data lives solely in that guild's own schema. Installs created on 0.53.5 or later never had these copies and are unaffected. **This upgrade cannot be rolled back** — take a backup first if you would rather keep the old rows around, and if you are upgrading from before 0.53.2, boot a 0.53.x release once on the way through as its startup notice instructs.

### Fixed

- **The Focus list on My Tasks stayed empty even with overdue work waiting.** It only counted tasks someone had moved to To Do or In Progress, and Backlog is where a new task starts — so on an ordinary setup it had nothing to show. It now looks at every unfinished task, whatever column it sits in. It also reads dates the way the task table beneath it does: work whose start date has arrived belongs on the list even if nobody gave it a due date.

## [0.61.3] - 2026-08-11

### Fixed

- **Completing a recurring task that carries tags failed with a server error.** Dragging such a task to a Done column (or otherwise marking it complete) returned a 500 and the next occurrence was not created. Only recurring tasks with at least one tag were affected, which made it look like a single project was broken.

## [0.61.2] - 2026-08-11

### Changed

- **Building a project from a template now reschedules its tasks.** Task start and due dates in a template are treated as relative: give the new project a start date and each task lands the same distance from it as it sat from the template's start — a task due three weeks in stays three weeks in. A template without dates of its own anchors on its earliest scheduled task, and giving only an end date anchors the schedule on the end instead. Leave the new project undated and task dates copy across unchanged, as before. Template task start dates, previously dropped, now carry over too.

## [0.61.1] - 2026-08-10

### Fixed

- **Signed-out visitors could not reach the sign-in page on 0.61.0.** Anything that landed on the app without a valid session — a first visit, a shared link, or a session that expired in a background tab — spun on a blank unresponsive page instead of redirecting, with no way to log in. The redirect away from the authenticated shell re-fired on every render, and a change in TanStack Router 1.170.19–1.170.25 stopped that redirect from settling, so it looped until the browser gave up. The router is pinned to 1.170.18 until the regression is fixed upstream.

## [0.61.0] - 2026-08-10

### Removed

- **The Gantt view has been removed from projects.** Task boards now offer Table, Kanban, and Calendar. Anyone whose saved view was Gantt lands on Table instead; nothing about the tasks themselves changes, and start and due dates are still shown in the Calendar view.

### Added

- **Spreadsheets can hold more than one sheet.** A tab strip along the bottom adds, renames (double-click a tab, or use its menu), duplicates, reorders, and deletes sheets — up to 64 per document. Formulas reach across sheets the way they do in Excel and Sheets: `=Sheet2!A1`, `=SUM(Data!A1:A20)`, and `='Q1 Actuals'!B2` for a name with spaces. Cross-sheet references keep working when things move — renaming a sheet re-spells every formula that named it, and inserting or deleting rows on one sheet shifts the references pointing at it from every other sheet. The name box also accepts `Budget!B4` to jump between sheets, and while typing a formula you can click a tab and then a cell to point at it. Excel export writes one worksheet per sheet; CSV, which can only hold a grid, exports the first sheet. Existing spreadsheets open unchanged as a single-sheet workbook.
- Tasks now record when they were completed. The timestamp is set when a task enters a Done status and cleared if it moves back out, so reopening a task no longer leaves it looking finished, and moving between two Done columns keeps the original completion time. Upgrading backfills tasks that are already complete from their last-modified date.
- **A Focus list at the top of My Tasks.** What actually needs doing now — work due soon plus anything urgent — with whatever you pin held at the top regardless of its dates. Ticking something off does not make it vanish: completions stay on the list, struck through, until the day turns over, alongside a running "3 of 6 done" count. Pin or unpin from either the list or the task table below it, set the date window and the urgent-work rule from the settings menu, and collapse the whole section if you would rather not have it. Every task matching your settings is shown, so a shorter list comes from a tighter date window rather than a hidden cutoff. The list spans all your guilds and is independent of the table's filters, so narrowing the table never empties it.
- **Projects can have a start and an end date.** Both are optional and independent — set either one, both, or neither when you create the project or later under Project settings → Details. When a project has dates they appear in bold at the top of the project page, next to its name and initiative; a project with no dates simply doesn't show the line. Duplicating a project or exporting and re-importing it carries the dates along.
- **Group a project's task table by tag.** "Group by" on a project's task list now offers Tag alongside Date window. A task sits under every tag it carries — one tagged both "bug" and "urgent" shows up in both groups rather than being filed under whichever tag came first — and tasks with no tags gather under Untagged. Each group is headed by the tag itself, in its colour. As with grouping by date window, manual drag-to-reorder pauses while a grouping is on; filtering, sorting, and bulk selection keep working, and a task selected in one of its groups counts once.

### Changed

- The linked-user picker on queue items is now a search, like every other person picker, instead of loading the initiative's whole roster up front.
- **Project settings → Details now saves everything at once.** The icon, name, description, and dates share a single "Save changes" button at the bottom of the tab, the way initiative settings already worked, instead of a separate save per section. Editing one section no longer discards unsaved edits in another. Tags still apply as you pick them.

### Fixed

- A start date later than the end date is now refused before saving, on both projects and tasks. The date pickers already stopped you choosing one, but a date typed into the field went through unchecked; the form now flags the range and keeps the save button disabled until it makes sense.
- Updated the document editor to Lexical 0.49, which brings table fixes (delete-line inside a cell, alignment applying both ways, and an optional sticky horizontal scrollbar on wide tables) along with selection fixes in read-only documents and in Firefox.
- Rebuilt every data table on TanStack Table v9. The tables themselves — task lists, document lists, the admin and settings tables — look and behave the same; the change is internal, moving sorting, filtering, grouping, pagination and selection onto the new feature-registration model. Row selection's "some rows selected" checkbox no longer stays half-ticked once every row is selected.
- Grouping a project's task table by tag no longer files every task under "Untagged". Picking a grouping from the toolbar moved the table but never told the page, so the page kept handing over its unfanned rows — none of which carry a tag to group on. Grouping by date window was unaffected, since those rows need no re-shaping.
- Dragging a card into a long Kanban column now changes its status. Once a column held more than about twenty cards the board drew only the ones on screen, and a drop into it could be credited to the last card the pointer crossed on the way in — so the card sprang back to where it started instead of moving. Columns that accumulate cards, Done most of all, were the ones affected.
- The calendar visibility dropdown no longer heads its list "My calendars". A calendar belongs to its initiative and is shared with the people in it, so the section is now simply "Calendars".
- Person pickers no longer show "User #12" where a name belongs. A selection the picker was handed rather than one you just made — the assignee filter you get back when you return to a project, a saved user property, the linked user on a queue item — is now resolved to a name and avatar against the same roster the dropdown searches. An id nobody in that roster matches still shows as an id, since there is no one to name.
- Pasting text that contains commas into a spreadsheet cell no longer splits it across neighbouring cells. Columns are now split on tabs only — the shape a spreadsheet writes when you copy a range — so a sentence lands in the one cell you selected. Pasted text with no tabs fills a single column, one row per line, matching how Excel and Sheets treat pasted CSV.

## [0.60.1] - 2026-08-06

### Fixed

- The 0.60.0 calendar migration failed on upgraded installs ("cannot drop column initiative_id of table calendar_events") because the pre-0.60 `recent_views` row-security policies still referenced that column. The migration now drops and re-renders those policies alongside the event-table ones; deployments stuck on the failed migration start cleanly on this release with no manual intervention.

## [0.60.0] - 2026-08-05

### Changed

- **The Events tool is now Calendars.** A calendar is a shareable container for events — like a project contains tasks — with its own name, description, and color. Sharing moves from individual events to the calendar: whoever can see a calendar sees its events, and whoever can edit it can create, edit, and move events inside it. Color belongs to the calendar too: events no longer carry their own color and always render in their calendar's. Attendees are unchanged (invitations and RSVPs stay per event) but never affect who can see an event. The calendar page lists your calendars alongside a derived, read-only calendar per project showing its task dates, each with its own visibility toggle. Existing events are preserved: every initiative that had events gets a renamable "Default Calendar" containing them, readable by all initiative members with initiative managers as owners — events that were previously shared more narrowly become visible to their whole initiative, so admins should move sensitive events into a restricted calendar after upgrading.

### Fixed

- Create buttons and initiative pickers for projects, documents, calendars, queues, and counter groups now consistently follow your actual per-initiative create permission. Members whose custom role grants creation see the affordances everywhere they apply, and buttons or picker entries the server would reject no longer appear.
- The calendar page now offers event creation in the all-initiatives view when you can write to at least one calendar — the create dialog picks the target calendar, defaulting to the one you used last.
- Platform staff acting in a guild through a scoped, time-bound access grant no longer see create buttons for new projects, documents, calendars, queues, or counter groups. Such a grant edits existing content only — the server already declined those creations, and the UI now reports the same answer instead of offering a dialog that fails on submit.
- The global "+" quick-create for documents and tasks (the bottom-bar menu and the command palette) now follows your create permission: its items hide when you can't create the thing in any of your guilds, and the wizards list only the guilds and initiatives you can actually create in — so you no longer walk through a wizard only to be refused on submit.

## [0.59.0] - 2026-08-03

### Changed

- **AI configuration is now connection-based with a single app-wide mode.** An operator chooses whether AI providers are configured at the **platform** level (the operator's connections apply to every guild), **per guild** (each guild admin configures its own), or **disabled** — one mode app-wide, mirroring the sign-in posture. A connection defines the provider, model, and an optional shared key; guild members attach **their own API key** and pick which connection they use, and never set the destination themselves. Standalone per-user AI (outside a guild) has been removed. An existing platform or guild provider is migrated into a connection automatically and its key is preserved; per-user AI keys are not migrated.

### Security

- AI provider credentials are now stored per member inside their guild's isolated database schema under row-level security, are never returned by the API (only whether a key is set), and are purged when a user is deleted or anonymized. A connection's destination (provider and base URL) is always set by the mode's owner, so a member's key is only ever sent to that owner-set destination. Every outbound AI call — subtask/description/summary generation, connection tests, and model listing — flows through the shared guarded egress that connects only to the policy-validated address; private or internal addresses are permitted only for an operator-configured local (Ollama) model, never for a guild admin or member.
- Personal API keys are now stored behind database row-level security and are reachable only through the system engine — the request path holds no grant on the table at all — matching the server-side session store. Creating, listing, deleting, and authenticating with API keys is unchanged.

## [0.58.3] - 2026-08-03

### Fixed

- The new-task dialog's **Status** dropdown now resets when you switch projects. Because the task section is reused as you move between projects, a status you had picked (or the previous project's default) could linger and be submitted against the new project, whose statuses have different ids. The composer now drops any status that doesn't belong to the active project and falls back to that project's default.

### Security

- Backup import now validates every upload asset key as a flat filename and uses one canonical key for its database lookup, uniqueness check, and storage write. A backup whose asset key carried path components is rejected as malformed, keeping an imported upload's database record and the stored file it points at in agreement.
- Hardened outbound webhook delivery and the custom AI provider so each request connects to the exact address validated against the target policy (https + public unicast); the original hostname is kept for TLS verification and the `Host` header. Both routes now share a single guarded egress helper.

## [0.58.2] - 2026-07-22

### Fixed

- The in-app MCP server's base64 filter now **nulls** `*_base64` fields instead of dropping the keys. Removing the keys made a tool's structured output violate its own (schema-required) shape, so every task or user-bearing listing failed with `'avatar_base64' is a required property`. The image blob is still stripped from the payload; the field is just kept as `null`.
- MCP list tools (tasks, `/me` tasks) now present their `conditions` and `sorting` parameters as JSON strings, so filtering and sorting through the MCP server work. They were typed as arrays (for the frontend), which the MCP request builder serialized with Python `str()` — single-quoted, invalid JSON — so every filtered or sorted list call was rejected with `QUERY_INVALID_CONDITIONS` / `QUERY_INVALID_SORT_FIELDS`.
- The cross-guild **My Tasks** / **Created Tasks** lists (`/me/tasks`, `/me/tasks/created`) now honor every `conditions` field — `due_date`, `title`, and the rest — instead of only a fixed handful (`project_id`, `priority`, `status_category`, `initiative_ids`, `guild_ids`, property values). Any other filter was silently ignored, so e.g. filtering "my tasks" by due date returned the full assigned list. The aggregate now applies the same filter set as the guild-scoped list, per guild.

## [0.58.1] - 2026-07-22

### Added

- The new-task dialog now matches the task editor: both are built on a single shared task form, so creating a task exposes the same fields as editing one. You can now set the **status**, attach **tags**, and fill in **custom properties** while creating a task — all saved in the single create request instead of only becoming available after the task exists.
- The single-project read (`GET /projects/{id}`) now includes the project's `task_statuses` (ordered by position), so a client has the status ids it needs to place or move a task without a second call or hunting through existing tasks. List responses stay lean and omit them. The MCP server also exposes the existing per-project task-status listing as a read tool.

### Changed

- In the task editor, tags and custom properties now save with the rest of the form when you click **Save** (previously they saved immediately on change). The editor warns before you navigate away with unsaved changes, and the new-task dialog no longer closes if you click outside it (use Escape or Cancel).

### Fixed

- The in-app MCP server now strips base64 image blobs (avatar and guild-icon data URIs) from every tool result. These `*_base64` fields carried no information an MCP client could act on yet often dwarfed the rest of a payload — a single guild icon was frequently larger than an entire task read — so filtering them out reclaims that context for the fields that matter.
- Relative timestamps across the app (e.g. "2 minutes ago" on task start/due dates, document cards and detail pages, comments, project activity, trash, import/export jobs, and the My Projects / My Documents lists) now refresh in place as time passes, instead of only updating on a page reload. A single shared clock drives every label, and each one re-renders only when its displayed text actually changes, so even large tables stay fast.

## [0.58.0] - 2026-07-21

### Security

- Platform role assignment is now enforced at the database layer: the request-path database roles carry column-scoped grants on the user table that exclude the platform role column, so role changes can only happen through the dedicated operator/owner role-assignment endpoint. Unused write privileges the request-path roles held on the user table were revoked outright. No behavior change for any existing flow; this is defense in depth, verified by CI invariants against the live catalog.
- Guild role assignment (promoting a member to guild admin) is now enforced at the database layer too. The endpoint runs on the system engine, and the shared guild database role no longer holds write access to change a membership's role — so a guild member cannot be elevated except through the guild-admin endpoint. Self-leave is scoped to your own membership, and request-path membership creation is pinned to a plain member. No behavior change for any existing flow; verified by CI invariants.
- Cross-guild access grants (the time-bound PAM / break-glass rows) can now only be written by the system-engine endpoints that already gate them by capability; the request-path database roles keep read access but no longer hold write access to the grants table. Defense in depth, verified by CI invariants.
- The per-guild and platform Postgres role-name prefixes (`GUILD_ROLE_PREFIX`, `PLATFORM_ROLE_PREFIX`) are now validated to identifier-safe characters at startup, so a misconfigured prefix fails closed at boot rather than reaching role-name DDL. Defense in depth (these come from operator config, not user input).

### Added

- Member pickers no longer download the entire guild roster: new slim, searchable, paginated endpoints serve member typeaheads (guild-wide, per-initiative, and per-project — the last scoped to the project's assignable write-access members), each returning just id, name, avatar, and status for a bounded page of results instead of every member's full profile. The assignee pickers (task edit, inline composer, bulk edit) and the assignee filter now search server-side against the project's members, the user-reference property picker searches its initiative's members, and the project/task pages no longer prefetch the full membership — so opening a project with thousands of members no longer transfers megabytes of inline avatars to render a dropdown. The task detail now carries its author inline (so the "Created by …" chip needs no roster lookup) and the trash owner-reassign picker lists the eligible owners returned with the prompt, so both drop their full-roster fetch too. Event attendee pickers (create dialog and settings) now use the same initiative-scoped typeahead. Mention autocomplete is server-backed too: the document editor's `@`-mention no longer loads the whole embedded member list (it searches the initiative's members on demand), the mention-search endpoint is now paginated in the same envelope as the other member searches, and both the document and comment mention pickers render member avatars.
- Multiple sign-in providers: the sign-in page now offers a button for every SSO provider the server has configured, not just one. Operators manage additional OIDC providers in Settings → Authentication — with presets for Google and Microsoft Entra, and a custom option for any OIDC identity provider (Keycloak, Authentik, Zitadel, …) — alongside the existing platform SSO form. Client secrets are write-only: set or replaced, never displayed.
- Per-guild authentication: on platforms configured for per-guild auth, guild admins get an Authentication tab to manage the guild's own OIDC identity providers (presets, write-only client secrets, and the guild's callback URL for IdP registration) and to require that members reach the guild only with a session signed in through one of them. An unsatisfied session gets a sign-in dialog that returns to the page it was on, and completing it upgrades the session in place — satisfying one guild never un-satisfies another. Requirements bind everyone (members, admins, and platform support alike) and are enforced in the database's row security across every surface — guild pages, cross-guild "my" views, realtime sockets (re-checked for the life of the connection), and media/download tokens — while long-lived integration credentials (API keys, device tokens, automation) deliberately never satisfy them. To prevent lockouts, an admin can only require a provider their own session has signed in with, and a required provider can't be deleted until the requirement changes. Outside per-guild auth posture the surface is absent entirely. Each guild also gets a shareable sign-in page (`/guild/{id}/login`, linked with a copy button from the Authentication tab): signing in through the guild's IdP admits the user to the guild as a plain member — provisioning their account on first sign-in when the provider allows it, honoring the guild's member capacity — so a single-guild user's entire login experience can live at their guild.
- Per-guild sign-in is now an operator entitlement. On per-guild-auth platforms the platform Guilds dashboard gains a per-guild toggle that turns a guild's Authentication surface on or off (the guild's own admins can't grant it themselves). Turning it off is non-destructive: the guild's providers are kept and existing members keep signing in through them — and any existing sign-in requirement stays enforced — it only closes the guild's auth-config surface and stops new accounts onboarding through the guild's IdP. The toggle appears only under per-guild auth posture.

### Changed

- The platform single sign-on configuration now lives on its provider-registry entry — the same registry that backs additional and per-guild providers — instead of a parallel copy in app settings kept in sync behind the scenes. The settings page, login, and background sync all read one record now; the migration folds any existing configuration in automatically and the settings screen is unchanged. `OIDC_*` environment values still pre-fill the provider on first boot only.
- Accounts created through single sign-on no longer carry an unusable placeholder password — they store no password at all, and password login for such an account is simply refused until one is explicitly set. The legacy per-user OIDC columns (superseded last release by the per-provider identity links) are dropped; the migration re-copies any not-yet-migrated data first, so upgrades that skipped a release lose nothing.
- Login posture (platform-wide vs per-guild sign-in) is now a deploy-time setting (`AUTH_SCOPE`), read once at startup, rather than a runtime toggle in platform settings. The Authentication settings page shows the active posture as a read-only badge; the "coming soon" per-guild radio and its endpoint are gone. Posture is infra-agnostic — nothing about a specific host or vendor is baked in.
- The sidebar and the initiatives landing page no longer download every document (and, on the landing page, every project) just to show per-initiative count badges. New grouped-counts endpoints return the per-initiative totals in one query, honoring the same visibility rules as the lists — so the badges stay accurate while large guilds stop transferring their whole corpus on every page. The sidebar's queue and counter-group badges use the same endpoints now too, replacing capped list fetches that silently undercounted past 100 items and dragged each item's full sharing state along.
- The "new document" and wikilink dialogs no longer download every document in the guild to populate their template picker. Both pickers are now searchable typeaheads backed by the server: templates are filtered in SQL (by template flag and document type) and searched by title across the whole guild, so opening the dialog fetches a bounded page instead of the entire document corpus. Picking a template for a whiteboard or spreadsheet no longer lists text-document templates. The documents list gained the same filters for callers that need them.
- The guild projects list no longer loads every visible project's full object graph just to filter and paginate it in Python. The `archived`/`template` filters, ordering (per-user manual order), and pagination now run in SQL, so a page fetches only the rows it returns and the reported total is exact rather than truncated. A `search` param (name substring, matching the "my projects" list) and an opt-in `slim` projection (id, name, icon, initiative, and your permission level — without documents, grants, tags, or the nested initiative) let project pickers and similar list-only callers fetch a bounded, lightweight page.
- Task pickers no longer download full task rows just to show a title list. A new slim task typeahead (id + title, searched by title in SQL and scoped to an initiative or the whole guild) backs the queue item's linked-task picker and the command palette's task search, so each keystroke fetches a bounded, lightweight page instead of every matching task's assignees, status, tags, properties, and comment counts.
- Sidebar rows use their full width: an initiative, project, or tool row's name and count now span the whole row until you hover it, at which point the settings/"+" button slides in and the name shrinks to make room (rather than the button permanently reserving space or overlapping the text). The reveal animation is skipped for users who prefer reduced motion.
- Export menus in tool headers now group their formats under a "Backup" heading (the importable JSON envelope) and a "Report" heading (PDF, CSV, Excel, Markdown, and other renderings), so it's clear which download can be re-imported.
- Calendar pages now load events and task markers in a single request instead of two. New `calendar-entries` endpoints (per-guild and cross-guild "my calendar") return the union of calendar events and in-window task start/due markers over the visible date range, each leg still gated by the same per-resource access rules as the standalone lists. The Events page and My Calendar consume the aggregate through one query; My Calendar now also windows its tasks to the viewport and shows every in-window task rather than only the first page.

### Fixed

- Signing in through single sign-on no longer sends the app into a request storm: the sign-in callback finished, updated the session, and then re-ran itself off its own update, re-fetching the current user, the guild list, and access grants dozens of times before settling. The callback is now consumed exactly once, and the guild list no longer reloads every time the current user is refreshed.
- Comment, document-summary, and guild-list error messages now route through the shared error-message helper: the user sees a localized message (and rate-limit errors are surfaced as such) instead of an untranslated backend error code.
- A database created or restored in a Postgres cluster where the platform "admin" → "operator" role rename had already run no longer loses its platform-staff row-security coverage: a repair migration finishes the rename by re-binding the affected policies (access-grant queue, platform user list/management) to the operator role and removing the leftover one. Without it, operators and owners saw only their own rows in the access-grant queue and the platform user list on such databases.
- The sidebar "Edit tag" dialog is no longer visually broken — the name field now fills the row and the color picker sits beside it, instead of the color picker taking the full width and collapsing the name field to a sliver.
- On mobile, opening the three-dot menu next to an initiative or project in the sidebar no longer dismisses the sidebar drawer.
- Removed redundant spacing between icons and labels across buttons throughout the app; the button's built-in gap now handles it consistently.
- The "My Tasks" page no longer returns a 500 error when filtered by a custom property. The cross-guild task views load property definitions per guild schema now, instead of querying a table that isn't visible on that request's connection.
- The dashboard's "Upcoming tasks" list no longer sorts urgent tasks last. It sorted by a hand-rolled priority map that omitted `urgent` (and invented unused `critical`/`none` keys), so every urgent task fell into the fallback bucket and sorted after lower-priority ones. Priority ordering now flows from a single source of truth in `lib/sorting.ts`, derived from the backend `TaskPriority` enum, that every priority-list UI shares — so it can't drift again.
- The "My Documents" page's data fetching now routes through the shared API client wrapper like its sibling "My Projects"/"My Calendar" views, instead of a hand-rolled fetcher that bypassed it — so native (Capacitor) base-URL rewriting and request handling apply consistently.

## [0.57.0] - 2026-07-16

### Added

- Tags on every tool: queues, counter groups, and advanced tools can now be tagged, joining projects, documents, calendar events, tasks, and queue items. Each tool's settings flow gained a tag picker, its lists show tag chips, and tag support is now wired automatically for any future tool (drift-tested against the tool registry).
- Bulk tag edit is a single atomic operation: one request adds/removes tags across the whole selection server-side. A failure (for example a tag someone else just deleted) changes nothing — no more half-applied batches — and a bulk edit no longer floods other viewers with one refresh per item.
- Sidebar tag editing: a pencil toggle in the Tags header switches the sidebar tag browser into edit mode — rename, recolor, or trash any tag inline, with a select-all checkbox and bulk delete — no need to visit each tool that uses the tag. The separate expand-all/collapse-all buttons merged into one toggle.
- Backup restore: a whole initiative or guild backup zip can be imported by a guild admin. Upload shows a pre-flight plan (source guild, per-initiative content counts, file payload size) before anything is applied; confirming restores each backed-up initiative as a NEW initiative (renamed on collision, tool switches from the backup, the importer becomes its manager), with uploaded files restored into guild storage (deduplicated and quota-checked) and every entry applied through the same importers as single-file imports — a corrupt entry fails alone and is reported, never the whole restore. Unconfirmed uploads expire after 24 hours.
- Data import: every exported JSON envelope — projects, documents (text, spreadsheet, whiteboard, link), queues, counter groups, and calendar events — can now be imported into an initiative of your choice. Tags and custom properties match by name (or are created), people resolve by email against the target initiative's members with unmatched ones reported, and the importer becomes the owner of everything created. Small files import instantly; large ones run as a background job with an inbox notification when done. Requires the tool's create permission in the target initiative; 0.56.x-era exports (the old `kind` spelling) import unchanged.
- Import surfaces: each tool's list page (documents, projects, queues, counter groups, calendar) gained an "Import from file" action — an overflow menu on the header and a button in the empty state — for importing that tool's JSON export. The backup import runs through a wizard in guild settings: pick a zip and it's previewed locally (nothing uploaded until you continue), then uploaded, planned, and confirmed.
- Guild settings **Data** tab: the former Export tab now hosts both directions — export and import — plus one activity table showing recent export and import jobs together, with re-download for finished exports and a report view for finished imports. The old `/settings/export` URL redirects here.

### Fixed

- Startup no longer fails with `permission denied for table guilds` (or, before 0.55, `new row violates row-level security policy for table "guilds"`) on installs that still have `PREVIOUS_SECRET_KEY` set. The boot-time secret-key sweep left an assumed per-guild database role on a pooled connection after committing, which blinded the startup seeding that ran next — it saw no guilds, tried to re-create the default one, and crashed the boot. The role is now transaction-scoped in the rotation sweep, the S3 upload backfill, and the local-upload relocation walk, so it can never outlive the work it was assumed for.
- Bulk tag edits could partially apply and error when the selection was edited from a stale view (for example after another member deleted a tag); the resulting event storm could also degrade the whole server.
- The tag list shown on tasks, projects, and documents right after saving tags now always reflects the save (it could briefly show the previous tags).
- Duplicating or cloning tasks, projects, and documents no longer carries over links to tags sitting in the trash.
- The documents "untagged" filter and count now treat a document whose only tags are trashed as untagged.
- Renaming or recoloring a tag now refreshes its chips everywhere immediately; deleting a tag refreshes all tools' lists, not just tasks.
- Imports now match existing tags case-insensitively, matching the duplicate rule the tag editor enforces.
- The calendar no longer drops tasks. It asked for the first 100 tasks in the initiative with no date filter at all, so a busy initiative could silently leave in-window tasks off the calendar entirely, while still transferring tasks from years you weren't looking at. It now fetches exactly the dates the current view shows (day, week, month, year, or list) and pages through all of them. The project filter's options now come from the initiative's projects, so they no longer appear and disappear as you move between months.

### Changed

- Startup now logs which Postgres login each of the three database connections uses, and warns loudly (without refusing to boot) on wiring that collapses the role separation: `DATABASE_URL_APP` and `DATABASE_URL_ADMIN` sharing a login, or the app login holding SUPERUSER/BYPASSRLS (for example, swapped connection strings). It also verifies the connected logins actually hold the audited shared-table privileges — a deployment connecting as non-standard logins now stops at boot with the exact `GRANT` statements to run, instead of failing later with a bare "permission denied" mid-request or mid-seeding. Creating the default primary guild in a database that shows signs of not being fresh (existing users or surviving guild schemas) now logs a warning naming the likely causes.
- The document and task pickers on queue items, and the project's "attach existing document" picker, now search as you type on the server instead of downloading every document and task in the initiative when the dialog opens. Opening a picker shows the most recent entries and typing narrows them; large initiatives no longer stall these dialogs. Project document cards now load only the documents actually attached (API: `GET /documents/` gained an `ids` filter, max 100 per request).
- The web app now renews your session silently in the background instead of interrupting you with a "session expired" sign-out when the short-lived access token lapses. You stay signed in as long as you use the app at least once every 30 days; signing out still ends the session everywhere immediately.
- Signing in (password or SSO) now issues the short-lived renewable session token directly, completing the new login model: the browser session rides the rotating refresh token instead of a single hour-long token. If the session store is briefly unavailable, sign-in falls back to the legacy token so nobody is locked out. Changing your password now keeps the device you changed it on signed in, while still signing out every other session immediately.
- Single sign-on account data (the IdP subject, refresh token, and sync timestamp) now lives on the per-provider identity links instead of the user row; a boot backfill migrates existing data automatically and nothing changes for signed-in users. The API's `UserRead.oidc_sub` field is replaced by a `has_federated_identity` boolean (read by the profile and deletion dialogs to hide the password confirmation for SSO-only accounts).
- The project import dialog now uses the shared import engine (API: `POST /projects/import` was replaced by `POST /imports/envelope`, which accepts every tool's envelope — the file's `type` field selects the importer).

## [0.56.1] - 2026-07-14

### Changed

- Export envelopes and backup manifests now use a `type` field as their format discriminator instead of `kind` (values unchanged, no schema version bump), and project backups carry `type: "initiative-project"` like the other tools. Files exported by 0.56.0 still import: the editor's import accepts both spellings, and project backups never depended on the field.

## [0.56.0] - 2026-07-14

### Added

- Data export: every tool — documents, projects, tasks, queues, counter groups, and calendar events — can be exported straight from its page in type-appropriate formats.
  - Report formats: PDF (set in the app's typeface, with the guild's name and icon in a running header), CSV, Excel (XLSX), Markdown, and Word (DOCX) for text documents. Report content is localized (English, German, Spanish, French) and timestamps use your time zone.
  - Importable backups: JSON envelopes for text documents, whiteboards, spreadsheets, smart links, projects, queues, and counter groups (each carrying the entity's tags and custom properties where it has them), and the original file for uploads. A whiteboard envelope's content is a standard Excalidraw file, so unwrapping it opens anywhere Excalidraw runs. The editor toolbar's import accepts both the envelope and legacy `.lexical` files. Whiteboards additionally export PNG/SVG images, rendered in the browser.
  - Tasks export the current view — same filters and visibility as on screen, or just the selected tasks — as a table, a checkable Markdown task list, or a detailed one-task-per-page PDF carrying the full record: description (rendered as Markdown), subtasks, threaded comments, assignees, tags, and dates. Queues export their turn order with current/held/hidden entries marked; counter groups export their values and bounds.
  - Bulk selection: select multiple documents, projects, queues, counter groups, or calendar events and export them all at once. The documents grid and tag views gained the same card selection (and full bulk toolbar) as the other lists.
  - Calendar events export as a standard iCalendar (.ics) file (recurrence rules and attendee RSVPs preserved) or an importable JSON envelope — for a selection, one initiative, or every event you can see. Event sharing rules apply throughout: an export only ever contains events shared with you.
  - Delivery: small exports download instantly; large ones run as a background job, and an inbox notification delivers the file if you navigate away. Artifacts are private to their creator (guild admins can see their guild's), expire after 7 days, and spreadsheet formats carry injection protection. Read access suffices everywhere except project backups, which require write.
  - Whole-initiative and whole-guild exports: one zip containing either an importable backup — every tool's JSON envelope in per-initiative folders, indexed by a manifest, optionally bundling the file uploads your documents reference — or an à-la-carte report with a per-tool format choice (a project PDF beside a queue CSV beside a calendar ICS). Guild-wide export is guild-admin only (re-checked when the job renders); sharing rules apply within each initiative, projects you can only read are included in backups, and a pre-flight estimate reports per-tool counts and the uploads payload size.
  - Export wizard: an Export tab in initiative settings (managers and up) and a new Export tab in guild settings (admins) walk through those exports — pick backup or report, toggle tools with live item counts, see the uploads footprint before committing, and choose report formats per tool (documents split by text/spreadsheet type). Exports run in the background; closing the dialog doesn't cancel them.
  - The guild settings Export tab also lists recent exports (guild admins see every member's), so finished artifacts can be re-downloaded until they expire — no more losing a download to a closed tab.

### Changed

- Project backup (JSON) export now runs through the export engine: large projects export as a background job with the inbox-notification pickup instead of one long request, and artifacts follow the same private-to-creator delivery and 7-day expiry. The downloaded file and the import flow are unchanged. (API: `GET /projects/{id}/export` was replaced by `GET /exports/project?project_id=…`.)
- The calendar's ICS export moved onto the export engine (API: `GET /calendar-events/export.ics` was replaced by `GET /exports/calendar-event?format=ics`); the cross-guild `/me/calendar-events/export.ics` feed is unchanged.
- The queue page header now matches the other tool pages: a labeled Settings button sized like its neighbors, with queue deletion living in the settings page (where it already had a confirm dialog) instead of a header trash icon.
- The app's font (Outfit) is now bundled with the app instead of loaded from Google Fonts, so pages render without contacting any third-party host — including on air-gapped or intranet deployments.

### Fixed

- The advanced tool's Create button now works. The sidebar "+" and the "New Advanced Tool" button (in the tool tab) were previously a disabled placeholder; they now open the connected tool's embedded page on its new-item screen, where the tool is built. Nothing is created on our side until it's saved there.
- Guild admins can now load the member roster of initiatives they haven't joined. The roster API returned 403 for them — every other initiative read already honored the guild-admin override — which left the linked-member and assignee pickers empty when an admin viewed another member's initiative.
- Boot now heals missing shared-table grants for the system engine. Startup now re-asserts the audited `system_grants` registry for `app_admin`/`app_user` (tables and their row-id sequences), idempotently and additively — completing the issue #835 fix.
- The editor's emoji picker no longer breaks when the search text contains characters like `(` or `[`, and suggestions now match on the emoji's name as well as its keywords.

### Security

- All GitHub Actions in the CI/release workflows are pinned to full commit SHAs.
- Chart theme styles are validated by the browser's own CSS parser before being applied (defense in depth; no user-facing change).

## [0.55.0] - 2026-07-12

### Added

- Per-guild user limits (default unlimited), set from the admin dashboard's Guilds tab. At the cap, new joins/invites are refused; existing members and SSO auto-provisioning are unaffected.
- Per-guild lifecycle status for moderation holds: `read_only` blocks writes, `suspended` hides the guild from members (admins keep settings access). Reversible; never touches stored data.
- Support/moderator access grants are now database-enforced: read grants are read-only; read_write grants can edit content but not membership, roles, or sharing.

### Changed

- Renamed the platform **Admin** role to **Operator** so it no longer collides with a guild's **admin** role. The platform ladder is now `member → support → moderator → operator → owner`; capabilities and behavior are unchanged. A migration renames the `users.role` value and the `platform_admin` database role in place, so existing platform admins become operators automatically — no action needed.
- Operator "delete this guild" is now scoped to the deleted user's solely-admined guild instead of accepting any guild id.
- Removed the `ALGORITHM`, `COOKIE_NAME`, `REFRESH_COOKIE_NAME`, `PROJECT_NAME`, and `API_V1_STR` settings — their values are now fixed. Drop them from your `.env`; leftovers are ignored.
- Removed the `OIDC_REDIRECT_URI` and `OIDC_POST_LOGIN_REDIRECT` settings (read by nothing — redirect URLs derive from `APP_URL`) and the legacy `OIDC_DISCOVERY_URL` alias. OIDC is configured in Settings → Admin; the `OIDC_*` env vars only pre-fill it on first boot. If you still set `OIDC_DISCOVERY_URL`, use `OIDC_ISSUER` instead.
- `backend/.env.example` was rewritten; optional OIDC/SMTP/S3 lines are commented out so placeholder values no longer seed the admin settings on first boot.
- SSO (OIDC) sign-in now fully verifies the provider's identity token (signature, issuer, audience, expiry, nonce) and links accounts by the provider's stable subject id instead of email. No action needed; existing logins keep working.

### Deprecated

- A superuser (or `BYPASSRLS`) role in `DATABASE_URL` is deprecated; a future release will refuse to start with it. To migrate: run `backend/scripts/create-provisioner.sql` once (`-v provisioner_password='<password>'`), point `DATABASE_URL` at `app_provisioner`, restart. Fresh docker-compose installs already do this.
- Removed the unused `AUTO_APPROVED_EMAIL_DOMAINS` setting (read by nothing). Drop it from your `.env` if present.
- Removed the `MAX_UNBOUNDED_PAGE_SIZE` setting — "fetch all" list responses are now served in bounded windows that the app pages through automatically, so there is nothing to tune. Drop it from your `.env` if present.

### Fixed

- Deleting a user's blocking guild from the admin user-deletion dialog no longer freezes the page (and silently does nothing): the UI dependency tree carried three copies each of Radix's focus-scope, dismissable-layer, and focus-guards packages, so the nested confirm dialog and the outer dialog couldn't see each other — fighting over focus in an infinite loop, dismissing each other on clicks, and leaving the page permanently unclickable. Each is now pinned to a single copy, which also protects every other nested dialog/confirm combination.
- Guild admins of a suspended guild are no longer trapped on its settings page: the redirect that pins a suspended guild to settings fired against the pending navigation target, cancelling every attempt to reach another guild or a personal page. It now only applies within the suspended guild's own routes. PAM/break-glass grantees are exempt from the pin entirely — a grant browses a suspended guild like an active one (the backend never blocks grant access on lifecycle status), so grantees now reach its content instead of being stranded on a settings page they can't view.
- Read-only guilds no longer offer create buttons the server would refuse: documents, projects, queues, counter groups, and events hide their create affordances while the guild is frozen. Queue, counter, and event error toasts now surface the actual reason (e.g. "Guild access denied") instead of a generic "something went wrong".
- Newly registered users are no longer bounced from the home page to the documents page with the "create document" dialog open: the create-document wizard's auto-advance no longer runs while its dialog is closed. The create-task wizard shared the same defect (silently pre-fetching and advancing while closed) and was fixed alongside it.
- Task boards, document pickers, and project lists with more than 1000 items no longer silently lose rows: "fetch all" list requests now walk bounded server windows until the complete set is retrieved, and truncation is always reported via `has_next`.
- `backend/scripts/create-provisioner.sql` missed the per-guild support roles: after switching `DATABASE_URL` to `app_provisioner`, deployments with existing guilds failed to boot with `permission denied to grant role "guild_N_support"`. If that hit you, run the fixed script once against your app database, connected as the Postgres superuser: `psql -v ON_ERROR_STOP=1 -U <superuser> -d <app-db> -v provisioner_password='<your password>' -f backend/scripts/create-provisioner.sql`. Running it again on a healthy install changes nothing.
- Guild storage caps, member limits, tier label, and lifecycle status can no longer be edited through guild-facing settings — they are platform-operator inputs, now enforced with column-scoped database grants.
- Anonymizing or deleting a user now scrubs their email from guild invites addressed to them, and neutralizes the invite so it can't become an open shareable link.
- Startup no longer fails with an RLS error when `DATABASE_URL_ADMIN` has lost its `BYPASSRLS` attribute (typical after restoring from a dump, #835): boot restores it automatically when possible, and otherwise prints the exact `ALTER ROLE` command to run.
### Security

- Block guild admins from changing a user's account `status` through the generic `PATCH /g/{guild_id}/users/{user_id}` edit endpoint. The handler already rejected platform `role` changes there, but `status` fell through to the field-assignment loop, so a guild admin could deactivate or anonymize any co-member — including the last platform admin — bypassing the dedicated deactivate/reactivate flow and its guards (last-admin protection, ownership transfer, confirmation). Status changes now return HTTP 400 and must go through the delete/approve endpoints.

## [0.54.2] - 2026-07-04

### Fixed

- **Notifications work again.** The 0.54.0 least-privilege database refactor revoked the bare login role's access to the `notifications` and `push_tokens` tables, but the notification and push-token endpoints still ran on that role — every request failed, so the bell showed no notifications (the backlog looked cleared; it was never deleted and reappears with this fix), nothing could be marked read, and mobile push registration failed. These endpoints now run on the authenticated platform path like the rest of the API, and unregistering a push token is scoped to the calling user's own tokens.
- Permanently purging a document (manual trash purge or the retention worker) now unresolves wikilinks pointing at it in every other document — including trashed ones — instead of leaving links that reference a document that no longer exists.
- Expired sign-in and verification tokens are now cleaned up automatically by an hourly background sweep; previously expired rows accumulated indefinitely.
- Deleted (anonymized) users now display consistently as "Deleted user" everywhere; several screens previously showed a raw email or "Anonymous".
- Anonymizing a user now scrubs their display name out of content that embedded it as text — @-mentions in comments, mention nodes in documents, and pending assignment-digest emails — instead of leaving the name readable after the account was "forgotten".
- Hard-deleting an already-anonymized user now removes their guild-scoped data (task assignments, sharing grants, authored-content reassignment, …). Anonymizing drops guild memberships, and the deletion sweep only visited membership guilds, so it silently skipped everything.

## [0.54.1] - 2026-07-04

### Added

- Calendar events now appear in the recent-items tabs bar, like projects, documents, queues, and counter groups.
- Calendar events and the advanced tool now appear in the command palette (⌘K) — events are searchable like other tools; the advanced tool gets one jump entry per enabled initiative.
- Initiative pages have an advanced-tools tab listing the initiative's advanced tools, with the standard Select → Edit access bulk-sharing flow (creation still happens in the connected automation service, and the UI says so).
- Counter groups can now be created from the mobile initiative menu, matching the other tools.
- Hard-purging an advanced tool (manual trash purge or the retention worker) now notifies the connected automation backend so its scheduling mirror is deleted too — including tools swept away by an initiative purge. Configured via `ADVANCED_TOOL_BACKEND_URL` + `ADVANCED_TOOL_PURGE_SECRET` (HMAC-signed, best-effort; unset on the default OSS image). Soft delete and archive stay pull-based — the automation side discovers them by syncing.

### Changed

- **Canonical tool naming across the API (breaking, pre-v1).** Every per-tool name now derives from one canonical tool enum: initiative master switches (`events_enabled` → `calendar_events_enabled`, `counters_enabled` → `counter_groups_enabled`, `advanced_tool_enabled` → `advanced_tools_enabled`), role permission keys (`docs_enabled`/`create_docs` → `documents_enabled`/`create_documents`, `create_events` → `create_calendar_events`, `create_counters` → `create_counter_groups`, `create_advanced_tool` → `create_advanced_tools`), and the per-member permission flags (`can_view_docs` → `can_view_documents`, `can_view_events` → `can_view_calendar_events`, `can_view_counters` → `can_view_counter_groups`, `can_view_advanced_tool` → `can_view_advanced_tools`, plus the matching `can_create_*`). A guild migration renames the columns and rewrites stored permission keys; no compatibility shims. The advanced-tool embed handoff now reads `advanced_tools_enabled` and the `create_advanced_tools` claim — external embed backends must follow the rename.
- Permission keys, initiative switch fields, membership permission flags, and recents entity types are now all derived from the tool enum in code (with CI drift tests), so adding a tool wires every backend surface automatically.
- The frontend now defines each tool in ONE registry (`src/lib/tools.ts`) — an icon plus capability flags — and derives everything else from it (routes, i18n keys, permission keys, sidebar rows, command-palette groups, initiative tabs, recents, trash invalidation), with drift tests that fail naming exactly which surface a new tool is missing. Route URLs renamed to the canonical stems: `/events` → `/calendar-events` and `/my-calendar` → `/my-calendar-events` (no redirects, pre-v1).

### Fixed

- Trashed counter groups and counters now auto-purge after their retention window, like every other trashed item — previously they lingered in the database indefinitely once past retention.
- Restoring an item from the trash now refreshes the relevant list pages immediately — the restore invalidation used cache keys that didn't match the app's real query keys, so restored items only reappeared after a manual reload.
- The calendar event attendee picker no longer comes up empty. It now lists the initiative members who can access the event.
- Clearing the initiative filter (e.g. clicking "All Documents") now resets to every document without a manual refresh.
- Break-glass / PAM access now shows the granted guild in the switcher immediately, instead of requiring a page reload before the guild becomes reachable.

## [0.54.0] - 2026-07-03

### Changed

- **The app no longer needs a Postgres superuser — and there is no superadmin.** Fresh docker-compose installs create a least-privilege `app_provisioner` role (migrations + guild provisioning only) at first database init — in superuser context, where Postgres 15/16's privilege model requires role bootstrap to live — and point `DATABASE_URL` at it from the start. Existing deployments run `backend/scripts/create-provisioner.sql` once and switch `DATABASE_URL`; staying on a superuser keeps working but logs a boot warning. The internal superadmin flag is gone: the system database role follows PostgreSQL's standard trusted-batch model (bounded by explicit per-table grants — new tables give it nothing by default), background jobs and maintenance sweeps route into each guild under that guild's own scoped role, and the request-path role holds only the minimal shared-table access the sign-in and account-security flows use. The whole posture (role attributes, per-table access, row security) is verified by automated tests on every CI run. `FIRST_SUPERUSER_*` settings are renamed `FIRST_OWNER_*` (old names still accepted).
- **Per-request database context is now transaction-scoped.** The assumed role and tenancy variables die with each transaction and are re-applied automatically at the start of the next one, eliminating the stale-context-on-pooled-connection bug class and making transaction-mode connection poolers (PgBouncer ≥ 1.21) safe in front of the app — backend CI now runs the whole suite through one to keep it that way. Authorization snapshots held past a freshness bound now fail closed instead of executing on revoked access.
- **Database migration history squashed to a v0.53.5 baseline.** Fresh installs build the shared schema from a single baseline plus a `guild_template` schema, and never create the legacy public copies of guild content (tasks, projects, documents, …) — guild data lives only in per-guild schemas; existing deployments keep their frozen legacy copies untouched. Platform endpoints (`/users/me`, login/registration, platform admin) no longer read guild content — `initiative_roles` is populated only by guild-scoped endpoints. Guild-schema migrations are now autogenerated against a live template (`scripts/gen_guild_migration.py`) instead of hand-written, removing a class of drift.
- Faster boots on large installs: guild schemas already built by the current version are skipped by the startup sweep (set `FORCE_GUILD_BACKFILL=true` for a one-off full sweep).
- **Upgrade note:** deployments running a version older than **v0.53.2** must upgrade to any v0.53.x release and boot it once before upgrading to this version. The app refuses to start (with instructions) if the database is older.

### Removed

- Support for in-place upgrades from versions older than v0.30.0 (the `upgrade-to-baseline.sql` helper is gone; it remains available in older release tags). Upgrades from v0.30.0+ still step through a v0.53.x release as before.
- The one-time schema-per-guild startup data conversion (every deployment that can cross the v0.53.x floor has already converted).

## [0.53.5] - 2026-07-01

### Added

- **Bulk-edit access on projects, queues, counter groups, and calendar events.** Like documents, these now have a **Select** mode: pick several items, then **Edit access** to share them with people, roles, or all initiative members — in one step. The same tabbed dialog everywhere (People / Roles / All members, Viewer/Editor), and it only touches items you own or can edit. For calendar events, Select lives in the calendar's **list** view.

### Fixed

- **Documents shared with "all initiative members" now show on the project they're attached to.** The project view filtered attached documents with its own check that only understood per-person and per-role sharing, so a document shared with everyone in the initiative disappeared for members without a personal grant. It now defers to the standard document access rules (which also covers guild admins and Full-access roles).
- Chester toasts no longer overlay the bottom navigation pill and are limited to showing 2 at a time.

## [0.53.4] - 2026-06-27

### Added

- **Floating pill bottom navigation.** On phones the top toolbar (menu, search, recents) is replaced by a floating pill at the bottom of the screen with menu (showing your unread-notification count), search, and home buttons. A separate **add** button — shown on every screen size — opens the right "create" dialog for wherever you are (new task in a project, new project in the project list, new document, queue, queue item, counter, counter group, or calendar event), and expands to Add Task / Add Document everywhere else. It hides automatically when you can't create anything in the current view, and replaces the old bottom-right add buttons.

## [0.53.3] - 2026-06-27

### Added

- **Bulk-share documents with all initiative members.** The documents' bulk **Edit access** dialog has a new **All members** tab that shares — or removes sharing for — every selected document with everyone in its initiative in one step, at Viewer or Editor.

## [0.53.2] - 2026-06-27

### Added

- **Manage all of a guild's initiatives from one place.** Guild settings has a new **Initiatives** tab (admin only) listing every initiative with its member count, where you can archive, delete, or grant the Project Manager **Full access** for each one without opening each initiative individually.
- **Archive an initiative to hide it from the sidebar.** Archiving keeps everything intact (projects, documents, tasks, queues) but removes the initiative from the main sidebar for everyone; unarchive any time to bring it back. Available from the new Initiatives tab and from an initiative's **Danger zone** settings. Archiving is guild-admin only.
- **Per-guild storage limit.** A guild can now have a maximum total upload storage; uploads that would push the guild over its limit are rejected. Defaults to unlimited, so existing guilds are unaffected until a limit is set.
- **Set per-guild storage limits from the Admin dashboard.** Platform admins and owners get a new **Guilds** tab under Settings → Admin that lists every guild with its member count and current cap, where you can set (in GB) or clear each guild's maximum upload storage. Lowering a cap below current usage blocks further uploads but never deletes existing files.
- **Optional S3-compatible object storage for uploads.** Uploads can now be stored in an S3-compatible object store you point it at (a self-hosted Garage instance, AWS S3, R2, etc.) instead of the local filesystem, via `STORAGE_BACKEND=s3` and the new `S3_*` settings. The filesystem remains the default, so existing deployments are unaffected. See `docs/OBJECT_STORAGE.md`.
- **Zero-downtime migration from local to S3 storage.** A `python -m app.db.backfill_uploads_to_s3` job copies existing local uploads into the bucket (idempotent, content-type preserved, integrity-verified), and a new `S3_LOCAL_FALLBACK` setting serves any not-yet-copied blob from local disk during the cutover — so flipping a deployment with existing uploads onto S3 never drops a file. See `docs/OBJECT_STORAGE.md`.
- **Configure object storage from the UI.** Platform owners get a new **Storage** tab under Settings → Platform to choose the backend and enter all S3 settings at runtime (no env vars or restart needed), with a **Test connection** button and a **Backfill** button that runs the local→S3 migration. Saved settings override the environment variables, and the secret access key is stored encrypted and never returned to the browser.

### Fixed

- **Deleting a guild now also removes its uploaded files.** Previously a deleted guild's stored blobs were left orphaned on disk (or in the object store); guild deletion now sweeps the guild's storage namespace. Local uploads are also organized into per-guild folders (`uploads/guild_<id>/`), with any existing files relocated automatically on startup — no action needed.

## [0.53.1] - 2026-06-24

### Fixed

- Bug fix on updating permissions

## [0.53.0] - 2026-06-23

### Security

- **Permanent deletion (purge) is now admin-only at the database, not just in app code.** Emptying an item from the trash for good was gated only by an app-layer check; a `RESTRICTIVE` row-level-security policy now backs it on every soft-deletable item.
- **Changing your password now requires your current password.** This stops a leaked session token or API key from silently taking over an account by setting a new password. (Accounts that sign in only through your identity provider have no local password and are unaffected.)
- **A password change or reset now also revokes your API keys.** Previously, resetting a compromised account's password left any outstanding API keys working; a credential reset now deactivates them too, so a leaked key can't survive the response.

### Added

- **Full access for the Project Manager role.** Guild admins can now grant the Project Manager role **Full access** from an initiative's Roles settings. Members with that role can view and edit every item in the initiative — projects, documents, queues, counters, calendar events — even when an item isn't shared with them, and can manage who else has access. It applies only within that one initiative, and shows on each item's Share control as a locked editor that can't be removed. Only guild admins can turn it on, and only on the Project Manager role (so a manager can't grant it to themselves).
- **Scoped API keys (read-only and single-guild).** When creating an API key you can now mark it **read-only** (it can read but never write) and/or pin it to a **single guild** (it can only reach that guild's data). Recommended for machine credentials such as CI or an automation/MCP tool, so a leaked key has a limited blast radius. Existing keys keep full access.
- **Optional MCP server for AI assistants.** A new opt-in endpoint lets MCP-compatible AI tools (such as Claude Code) work with Initiative on your behalf — read your projects, tasks, and initiatives, and make a few safe edits (create a task, move a task, add a comment) — authenticated with your personal API key. It's **off by default** and enabled per deployment (`ENABLE_MCP`); every action runs as you, under the same permissions and access rules as the app, and a read-only API key can't make changes.

### Fixed

- Adding an option to a select / multi-select custom property lost input focus after each keystroke, so only one character could be typed at a time. Option rows are no longer re-keyed by the value being edited.
- Guild admins were wrongly shown "access denied" when opening (or saving edits to) a document they hadn't been explicitly shared on. The realtime collaboration connection didn't apply the guild-admin access bypass the rest of the app uses; guild admins now have full access to every document in their guild.

### Changed

- Sharing for projects, documents, queues, counters, and calendar events is now a single Google-Docs-style **Share** control — pick **All initiative members** (Viewer or Editor) or **Restricted** (specific people and roles), available from each item's settings and its create dialog. Replaces the separate role- and user-permission panels.
- Creating a custom-property option now asks only for a label; the stored option value is derived from the label automatically (and de-duplicated), removing the redundant Value field from the editor.
- The date picker now accepts a typed date — a text field at the top of the popover parses common formats (e.g. `2026-06-16`, `06/16/2026`, `Jun 16, 2026`) on Enter or blur — and exposes month/year dropdowns in the calendar header for quickly jumping across years instead of clicking month-by-month.

## [0.52.0] - 2026-06-16

### Security

- **⚠️ BREAKING: initiative content is now members-only, enforced by the database.** If you're in a guild but not a member of one of its initiatives, that initiative's projects, tasks, documents, and other content are now hidden from you (previously they were blocked but still visible as "exists"). This database change cannot be rolled back.
- **Initiative isolation now covers the last few gaps.** Some related data — project/document sharing and links, project tags, and per-user state like favorites, recent history, and reminders — was still reachable by guild members outside the initiative; it's now members-only like everything else. New initiative tables are required to carry these database rules going forward, so the gap can't reopen.
- **Platform-role RLS hardening (Phase 2).** The purely-platform tables (`users`, `access_grants`, `app_settings`) now enforce least-privilege at the database via per-tier `platform_<role>` policies instead of relying on the app layer alone: a member sees only their own user row, support+ can read all users, moderator+ can manage them, and app-wide config (`app_settings`: OIDC, SMTP, branding, platform AI) is owner-only to write

### Added

- **Rename built-in initiative roles.** The built-in "Project manager" and "Member" roles can now be renamed per initiative (e.g. "Project manager" → "Dungeon Master") from the initiative's Roles settings tab. The chosen name shows up wherever that member's role appears — rosters, badges, and the initiative list.
- **Configurable recent-items tab bar.** A new "Recent items in tab bar" setting (Profile → Interface) controls how many recently-opened items the header tab bar keeps and shows, from 1 to 100 (default 20). Right-clicking a tab now opens a context menu with Close, Close others, and Close all.

### Changed

- **Per-resource access grants are now a single table.** Direct access grants for projects, documents, queues, and counter groups were stored in eight separate per-resource permission tables; they are now one polymorphic `resource_grants` table resolved through a single centralized authorization path, which also brings calendar events under the same model. Existing grants migrate automatically on upgrade; pre-existing calendar events are seeded with default grants (the creator owns it, managers can edit, everyone else can view) so they stay visible to members. This database change cannot be rolled back.
- The platform users CSV export (`/admin/users/export.csv`) no longer includes the `initiative_roles` column. Initiative roles are guild-scoped; a platform-level user export now contains platform data only.

### Fixed

- **Guild admins and break-glass grant-holders now have default read/write access to all initiative content.** An admin (or an active PAM/break-glass grant) who wasn't explicitly listed on a project, document, queue, counter, or calendar event could see "no results" for that content even though their role grants full access. Access is now resolved the same way for every content type, so the admin/break-glass override applies uniformly instead of per-endpoint.
- OIDC claim mappings with the "initiative" target type showed an empty initiative dropdown after picking a guild, and saving such a mapping failed. The admin settings endpoint looked for initiatives and roles in the shared schema, where they don't live, instead of inside each guild's own schema; it now routes into every guild to list them, and the role dropdown is correctly scoped to the selected guild.
- Container failing to start on Synology NAS (and other runtimes that re-apply a stale `PATH` on image upgrade) with `start.sh: exec: uvicorn: not found`. The startup scripts now put the bundled virtualenv on `PATH` explicitly instead of relying on the image's `ENV PATH`.
- `adduser`/`addgroup` warning and failure for the default `PUID`/`PGID` of `1000` (`uid 1000 is greater than SYS_UID_MAX 999`); the container user is no longer created in the system-account range.

### Removed

- **Platform-wide role labels.** The branding setting that renamed "Admin", "Project manager", and "Member" app-wide has been removed in favour of per-initiative role names (above), which offer finer-grained control. The `app_settings.role_labels` column and the `GET`/`PUT /settings/roles` endpoints are gone.

## [0.51.1] - 2026-06-15

### Fixed

- Uploaded media (document files, featured images, and embedded rich-text images) that existed before v0.51.0 now resolves again. The v0.51.0 URL rewrite to `/uploads/{guild_id}/{filename}` ran before the per-guild schemas were created on first boot, so it migrated nothing and the old prefix-less URLs were copied into the guild schemas as-is (and 404'd). A new migration re-applies the rewrite in both `public` (per row) and every guild schema.
- Embedded PDFs now render. The PDF.js worker is bundled and served same-origin instead of loaded from a CDN, so the app's `script-src 'self'` Content-Security-Policy no longer blocks it (and it works offline in the native app).

## [0.51.0] - 2026-06-15

### Added

- **`SECRET_KEY` rotation.** `SECRET_KEY` encrypts stored data (emails, OIDC/SMTP/AI secrets) and roots the email-lookup hash, so it can't be swapped in place — a bare change would lock out every user and orphan those secrets. To rotate it, set `PREVIOUS_SECRET_KEY` to the old value, set `SECRET_KEY` to a new one, and redeploy: the app re-encrypts everything on startup (idempotent), or run `python -m app.db.secret_key_rotation` manually. Unset `PREVIOUS_SECRET_KEY` once the logs report 0 failures. A failed `SECRET_KEY` validation now spells out this path in the error.
- **`JWT_SIGNING_KEY` for independent session-token rotation.** Optional dedicated key for signing session/login JWTs; when set it decouples token signing from `SECRET_KEY`, so it can be rotated freely — the only effect is logging everyone out, with no impact on encrypted-at-rest data. Falls back to `SECRET_KEY` when unset, so existing deployments are unaffected.
- Expandable guild sidebar — the guild rail opens into a flyout showing each guild's full name and member count.
- German (Deutsch) interface language.
- Guild schemas are re-checked on every boot, so upgrades automatically add new tables to existing guilds.

### Changed

- **⚠️ BREAKING: cross-guild ("my") data moved to a new `/api/v1/me/*` API.** The personal views (My Tasks, Created Tasks, My Projects, My Documents, My Calendar, and user stats) are now served by dedicated `/me/*` endpoints, replacing the old `?scope=global`, `/projects/global`, `/calendar-events/global`, and `/users/me/stats` routes. **The personal calendar (iCal) export URL changed** from `/api/v1/calendar-events/global/export.ics` to `/api/v1/me/calendar-events/export.ics` — any subscribed calendar feeds or bookmarks pointing at the old URL must be updated. Direct API integrations calling the old routes must move to `/me/*`.
- **⚠️ BREAKING: guild-scoped API moved under `/api/v1/g/{guild_id}/*`.** Every guild-scoped endpoint — projects, tasks, documents, initiatives, queues, counters, tags, comments, attachments, imports, calendar events, task statuses, trash, and guild member management — now takes the guild in the URL path instead of resolving it from a single server-held "active guild". This lets separate tabs/windows operate in different guilds at once. The legacy `?scope=global` / `?guild_id=` query addressing and the `X-Resolved-Guild` echo header are removed; direct API integrations must move to the `/g/{guild_id}/…` paths (cross-guild "my" views stay at `/api/v1/me/*`).
- **⚠️ BREAKING: trash is split into a personal and a guild view.** Your own deleted items are now a cross-guild list at `/api/v1/me/trash` (the personal Trash page), while the all-of-guild view at `/api/v1/g/{guild_id}/trash/` is guild-admin only (no more `?scope=mine|guild`). Restore and purge are addressed per item by its owning guild.
- **⚠️ BREAKING: uploaded media is now served at `/uploads/{guild_id}/{filename}`.** Document files and embedded/featured images carry their guild in the URL so they render correctly on cross-guild pages (e.g. My Documents shows files from several guilds at once). Existing stored URLs are migrated automatically (`20260613_0103`); any hard-coded `/uploads/{filename}` links or external bookmarks must add the guild segment. Realtime sockets (events, queues, counters, collaboration) and document downloads likewise take the guild from the `/g/{guild_id}/…` path. User avatars and guild branding are unaffected (stored inline / as external URLs, never under `/uploads/`).
- **Each browser tab now holds its own guild, taken from the URL.** You can keep two tabs open in two different guilds at once — they no longer fight over a single shared "active guild". The server-held `active_guild_id` (and its `PUT /users/me/guild-context` endpoint) is removed entirely; downloads, embedded media, and live connections all resolve their guild from the page URL. The recent-items tabs bar still spans every guild you belong to.
- Notification emails and push messages are now sent in your language.
- The mobile sidebar follows your finger when swiping it open or closed.
- The assignee selector is now a searchable dropdown with checkboxes and avatar chips, matching the tag picker.
- Slim, styled scrollbars in the sidebars and on the kanban board.
- Transactional emails are easier to read: names and key details are bolded, and styling survives Gmail mobile.
- Guild admins now have complete read/write access to every initiative's projects, documents, tasks, and comments in their guild, regardless of initiative membership or per-item permissions. In initiative member settings they appear in a collapsed "Guild admins" group (greyed out, can't be removed) and can be promoted to project manager, but are never assigned a standard member or custom role.

### Fixed

- Guild admins can again create and manage projects and documents in initiatives they don't explicitly belong to (such as a guild's default initiative) — the create and visibility checks now honor guild-admin access instead of requiring a per-initiative role.
- My Tasks and Tasks I Created now sort correctly across guilds — tasks from every guild are merged and globally re-sorted by date window (Overdue, Today, This Week, This Month, Later) and due date, instead of being grouped guild-by-guild.
- A batch of schema-per-guild fixes: property definitions, uploads and document downloads, account deletion/deactivation cleanup, OIDC role sync, cross-guild calendars, and the "added to initiative" notification all read and write the correct guild's data again.
- The Initiative logo now displays in emails.
- Corrected malformed stored defaults for tag and task-status colors and icons.
- Spell-check dictionaries, Excalidraw whiteboard fonts, and the Swagger API docs page are no longer blocked by the Content-Security-Policy.
- Opening the user or theme menu from the sidebar footer on mobile no longer collapses the sidebar.

### Security

- Restored initiative-level access checks lost in the schema-per-guild cutover — leftover permission rows no longer grant access after someone is removed from an initiative.
- Email-bound guild invites can only be redeemed by the matching email address.
- HTTPS deployments now send HSTS; API docs can be disabled in production (`ENABLE_API_DOCS`); SMTP test errors no longer leak mail server details.
- Rate limiting now covers every route, and "return all rows" list requests are capped.
- Device, email-verification, and password-reset tokens are hashed at rest; device tokens now expire after 90 days of inactivity.
- Text fields are no longer HTML-encoded on save ("Foo & Bar" stays as typed) and are length-capped.
- CORS no longer reflects arbitrary origins, and a Content-Security-Policy is sent on every response.
- Validation errors no longer echo the submitted value (such as a password).
- Links in documents are restricted to safe protocols, so a stored `javascript:` link renders inert.
- Emails escape user-supplied names, so a display name can't inject a live link.
- `SECRET_KEY` is validated at startup (no placeholders, minimum 32 characters).
- CSV exports are protected against spreadsheet formula injection.
- Real-time updates only deliver events for the guild you're connected to, and logging out or resetting a password closes websocket sessions and other logins too.
- Upload hardening: size limits enforced while reading, 404 for files with no database record, short-lived scoped media tokens on native, and a cap on avatar size.
- OIDC logins require a verified email before linking to an existing account, and guild admins can no longer assign platform roles when creating users.

## [0.50.2] - 2026-06-08

### Added

- **Events can span multiple days.** A timed event's end can now fall on a later day (the 24-hour limit is gone). The create dialog and edit page gained separate end-date pickers, and the calendar draws a multi-day timed event across each day it touches — in week and day views it fills the time grid on every day (start day from its start time, full middle days, end day up to its end time) rather than sitting in the all-day bar.
- **Edit an event's tags.** The event settings page now has a tag picker (matching tasks and documents) to add or remove tags; changes save immediately.

### Changed

- **Event reminder and invitation times now show in your timezone.** Event notification emails and push messages (invitations, reschedules, cancellations, and reminders) previously printed the start time in UTC. They now render in the recipient's own timezone in a more readable form (e.g. "Wed, Jul 1, 2026 at 2:30 PM PDT").
- **Creating an event adds you as an attendee by default.** The event creation dialog now starts with you in the attendee list (you can still remove yourself).
- **Changing an event's start time keeps its length.** Adjusting the start time shifts the end by the same amount, preserving the event's duration (including multi-day spans) instead of forcing it back to one hour.
- **Consistent date, time, and color pickers for events.** The event edit page now uses the same calendar date pickers, half-hour time selectors, and color picker as the create dialog.
- **Declined attendees stop getting event notifications.** If you decline an event's invitation, you no longer receive its reschedule, update, or cancellation notifications — matching reminders, which already skipped declined RSVPs.

## [0.50.1] - 2026-06-08

### Fixed

- **Mobile app "Reload now" no longer hangs on the splash screen.** After the splash-covered OTA reload landed, tapping "Reload now" showed the splash for ~60 seconds and then re-displayed the same "New Version Available" dialog without applying the update. The reload waited for the downloaded bundle to report a `success` status that Capacitor only assigns *after* a bundle boots and confirms itself — a freshly downloaded bundle is `pending` — so the wait always timed out. The update now applies as soon as the bundle is downloaded and ready.

## [0.50.0] - 2026-06-08

### Added

- **Drag and drop to reschedule on the calendar.** On both the initiative and project calendars, drag an event or task to a different day in month view (its time of day is kept), or onto a specific day-and-time slot in week view, or to a different hour in day view — rescheduling it without opening it. A plain click still opens the item.
- **"Add Event" button on an initiative's calendar.** A floating Add Event button (matching the existing Add Task button) now appears on an initiative's Events page for members who can create events.
- **Tags on the calendar list view.** Tasks and events in the calendar list now show their tags.
- **Event notifications for attendees.** You now get a notification (bell, plus email/push if enabled) when you're invited to an event, when an event you're attending is updated or rescheduled, and when one is cancelled. Organizers are notified when an attendee responds to their invitation. A new "Events" category in notification settings controls the email and mobile channels.
- **Event reminders.** A new "Event reminders" notification category sends a reminder before events you're attending begin, with a configurable lead time (at the time of the event, 5/10/15/30 minutes, 1 hour, or 1 day before — defaulting to 15 minutes).
- **My Calendar tasks toggle.** The My Calendar view gained a Tasks toggle (matching the initiative calendar) to show or hide tasks, and a My Calendar entry was added to the command center.

### Changed

- **The chosen calendar view now persists.** Switching between day, week, month, year, or list view is remembered across sessions and devices, and shared across the Events, My Tasks, and Created Tasks calendars.
- **Tasks clearly distinguish start from due on the calendar.** Start and due dates are labeled "Start"/"Due" with distinct markers, and a task that both starts and is due on the same day now renders as a single block spanning its time slot instead of two all-day entries.

## [0.49.9] - 2026-06-06

### Added

- **Pride month mode. HAPPY PRIDE!** The Initiative logo becomes an animated rainbow gradient — a flowing, softly glowing mark that appears everywhere the logo does (sidebar, sign-in, registration, landing). The "initiative" wordmark flows the same rainbow, and primary buttons gain an animated rainbow outline (their fill and label stay solid for readability). It turns on automatically during June (Pride Month) and can be set to always On, always Off, or Auto from the appearance menu (the sun/moon toggle). The animation respects the system "reduce motion" setting.

### Fixed

- **Native app: in-app updates now apply reliably instead of re-prompting.** When the app downloaded a new version and you tapped "Reload Now," the reload sometimes failed to take and the update dialog reappeared. The app now shows a splash screen that covers the entire reload — waiting for the new version to finish downloading and verifying before swapping it in — so the update applies the first time. (Reaches existing installs after a store/APK update.)

## [0.49.8] - 2026-06-05

### Added

- **Formula bar above the spreadsheet grid.** A name box (left) shows the active cell or selected range — type a reference like `B12` or `A1:C3` and press Enter to jump there — and an editable formula bar (right) shows and edits the active cell's underlying formula or value, so you can see a formula even though the cell displays its computed result. Editing works from either the bar or the cell, and clicking cells to insert references (point mode) works while editing in the bar. The cell/range indicator that used to live in the formatting toolbar now lives in the name box.

### Fixed

- **Dragging the spreadsheet fill handle on decimals no longer produces values like `0.30000000000000004`.** Numeric fills now round each generated value to the decimal precision of the source cells (so `0.1`, `0.2` fills to `0.3`, `0.4`, `0.5`, …), eliminating the floating-point drift that previously surfaced in the filled cells.

## [0.49.7] - 2026-06-05

### Added

- **Formula reference highlights and click-to-insert in spreadsheets.** While editing a cell formula (one starting with `=`), each cell or range it references is outlined on the grid in a distinct color, and the matching reference text in the cell is colored to match. Click another cell to drop its reference into the formula, drag or shift-click to insert a range (`A1:B3`), and click again to move the just-inserted reference — so you can build formulas by pointing instead of typing.

## [0.49.6] - 2026-06-05

### Fixed

- **Add Project from an Initiative's Projects tab now always creates the project in that initiative.** Previously the new-project dialog showed the initiative you were viewing, but — when the initiatives list was already cached — could create the project in a different initiative.
- **The active-guild indicator pill shows again in the guild sidebar on home pages.** A corrupted CSS class (spaces replaced by special characters) had made the highlight invisible.

## [0.49.5] - 2026-06-04

### Added

- **Drag the fill handle to fill cells in spreadsheets.** Grab the small square on the bottom-right corner of a cell or selection and drag down, up, left, or right to fill the range. Formulas adjust their relative references as they go (`=A1` filled down becomes `=A2`, `=A3`, …) while `$`-anchored parts stay put; numeric runs and `text + number` patterns extrapolate as a series (1, 2 → 3, 4, 5; `Item 1` → `Item 2`); anything else is copied. Double-click the handle to auto-fill down to the extent of the neighboring column's data. The whole fill is a single undo step and syncs to collaborators.

## [0.49.4] - 2026-06-04

### Fixed

- **Type straight into the next spreadsheet cell after Enter/Tab.** Committing a cell edit with Enter or Tab kept keyboard focus on the grid, so you can immediately start typing into the newly selected cell instead of having to click it first.

## [0.49.3] - 2026-06-04

### Added

- **Formulas in spreadsheet cells.** Start a cell with `=` to write a formula — arithmetic (`=A1+B1*2`, `=(A1+A2)/2`, percentages, exponents) plus common functions like `SUM`, `AVERAGE`, `MIN`, `MAX`, `COUNT`, `COUNTA`, `IF`, `ROUND`, and `ABS` over single cells or ranges (`=SUM(A1:A10)`). Cells show the computed result and recalculate live as their inputs change, including edits from collaborators; number formats (currency, percent, etc.) apply to results, and errors such as `#DIV/0!` or a circular reference (`#CYCLE!`) show in red with a tooltip. Inserting or deleting rows/columns rewrites references so formulas keep pointing at the right cells, and copying or exporting to CSV/XLSX emits the computed values.
- **Cut and move cells in spreadsheets.** Press Ctrl/Cmd+X to cut a cell or range — the source gets a dashed marquee and is left untouched until you paste, at which point the cells (formulas and all) move to the new location. Press Escape, copy, or start editing to cancel the cut.
- **Insert and delete spreadsheet rows and columns.** Right-click a row or column header in a spreadsheet document to insert a line before or after (above/below for rows, left/right for columns), or delete the selected line(s). The "Insert multiple…" submenu takes a count so you can add several rows or columns at once. Existing cells, styles, number formats, and frozen panes all shift to stay aligned, and selecting a band of headers first lets you insert next to — or delete — the whole range at once.

## [0.49.2] - 2026-06-03

### Added

- **Sort a spreadsheet by a column.** Right-click any column header in a spreadsheet document and choose "Sort A → Z" or "Sort Z → A" to reorder the whole sheet by that column, keeping every row's other cells (and their formatting) aligned. Blanks always sort to the bottom, and frozen header rows stay pinned in place.

## [0.49.1] - 2026-06-01

### Added

- **Shift+click range selection in data tables.** In selection mode you can now click one row's checkbox, then shift+click another to select every row in between (inclusive) in the order they're displayed.

### Fixed

- **Data table selection no longer desyncs when filtering.** Rows you select stay selected when you filter them out of view and then clear the filter — the checked boxes always match the selection used for bulk actions. The selection count also reads sensibly when a filter hides some of your selected rows (e.g. "5 selected (2 match filter)").

## [0.49.0] - 2026-06-01

### Added

- **Self-hosted over-the-air (OTA) app updates.** The native mobile app now downloads the web bundle that matches the backend it's connected to, so the frontend and backend stay in sync without reinstalling the APK for every release — no paid live-update service required. Each server build ships the matching Capacitor bundle; on launch and when returning to the foreground the app checks the server version and, if it differs, downloads the bundle and prompts "Reload now" (with a "Later" option). A failed update automatically rolls back to the previous bundle. When a release changes native code (not just web assets), the app detects that its installed shell is too old and asks you to update from the store/APK instead. Releases that only change web assets no longer rebuild the APK — they update entirely over the air.

## [0.48.1] - 2026-05-31

### Fixed

- Kanban drag-and-drop is more reliable: dragging a card to the top of a column no longer snaps it to the second slot.

## [0.48.0] - 2026-05-31

### Added

- **Graduated platform roles.** The two platform-level roles (`admin`/`member`) are replaced by a five-rung ladder — `member` → `support` → `moderator` → `admin` → `owner` — backed by a capability model so each platform operation is gated on the specific privilege it needs instead of a single all-or-nothing "admin" flag. App-wide configuration (OIDC, SMTP, branding, role labels, platform AI) now requires the `owner` role; user management, guild management, and role assignment are split across `moderator`/`admin`. Role assignment is bounded (you can't grant a role above your own), and the platform can never be left without an `owner`. Existing platform admins are automatically promoted to `owner` so no one loses access. The old single admin page is now split into two capability-gated areas: **Platform settings** (`/settings/platform` — auth, branding, email, AI; owner-only) and an **Admin dashboard** (`/settings/admin` — users and access; for support/moderator/admin), surfaced as separate entries in the sidebar menu and command palette.
- **Privileged Access Management (time-bound guild access).** Lower-privilege platform users (e.g. `support`) can now request temporary, per-guild access instead of relying on a standing all-guild bypass. A request specifies the guild, a read-only or read-write level, a duration, and a reason; an `owner`/`admin` approves, denies, or revokes it, and it auto-expires. Maximum duration is tiered by role for least privilege — `support` ≤ 4h, `moderator` ≤ 8h, `admin` ≤ 24h — enforced server-side and reflected as the preset options offered in the request form. Within the granted guild a grant acts like a time-boxed, read-only-or-read-write member: it reaches every initiative, project, document, queue, and counter group (consistently at both the RLS layer and the app-layer permission checks, so what a grantee can list they can also open). Grants are scoped at the database level (PostgreSQL RLS) to the one granted guild — read grants cannot write, owner-only operations stay blocked, and no grant can touch guild memberships, settings, or other identity/config tables, so a grant can never be used to escalate to guild admin. Requesters and approvers are notified in-app, by email, and via mobile push (when SMTP / FCM are configured) — each linking to the **Admin dashboard → Access** tab, which houses the request form and approval queue. Once a grant is live, the granted guild appears in the sidebar switcher marked as temporary (with a remaining-time tooltip); entering it shows a read-only banner and hides write affordances, and it disappears when the grant expires.

### Changed

- **Task reordering is now incremental and precise.** Dragging a task to reorder it sends only the moved task with a fractional "midpoint" position instead of renumbering and re-sending the entire list, so reorders are faster and no longer bump the `updated_at` of tasks that didn't move. Task order is stored at higher precision (NUMERIC) to allow many in-between insertions, with an automatic server-side rebalance when a gap is exhausted — matching how counters and queue items already order.

### Fixed

- Fixed two kanban drag-and-drop bugs in the project task board: you couldn't drag a card below the one directly beneath it (it snapped back), and you couldn't drop a card into the first slot of another column (it landed in the second). Drop placement now follows where the card is actually released — which half of the target card it overlaps — instead of inferring direction from list position, so every slot is reachable. List/table reordering was unaffected.

## [0.47.0] - 2026-05-29

### Added

- **Password complexity requirements.** New passwords must be at least 12 characters and are checked against the HaveIBeenPwned breach corpus via the k-anonymity API (only a 5-char SHA-1 prefix leaves the server). Enforced on registration, password reset, self password change, and admin user creation/update; no character-class rules per NIST SP 800-63B guidance. Existing accounts are grandfathered — short or breached passwords keep working at login until the next change. Disable the breach check by setting `HIBP_CHECK_ENABLED=false` in the backend env (e.g. for air-gapped deployments).
- **Task edit page shows who created the task and when.** A small avatar + "Created by {name} · {relative time}" chip sits inline with the task title (right-aligned, out of the way of the edit form). Hovering reveals the absolute creation timestamp. Follows the existing avatar conventions (deterministic colour fallback, anonymized-user handling, `User #<id>` fallback when the creator is no longer in the guild).
- Manual save button on document titles.
- **Version history for uploaded file documents.** Uploaded files (PDFs, Office docs, images) now keep a version history instead of being a single replaceable blob. A "Version history" popover on the file viewer lists every version (newest first) with its upload time; selecting an older version views or downloads it, and an inline trash button on each row deletes it. Anyone with write access can upload a new version (it must match the original file type); only the document owner can delete versions. Deleting the current version rolls back to the previous one; the last remaining version can't be deleted (delete the document instead). Old version blobs are cleaned up when the document is purged.

### Changed

- **Guild deletion is harder to trigger by accident.** The delete control moved off the first guild-settings tab into its own dedicated "Danger zone" tab, which now spells out exactly what deletion removes (initiatives, projects, tasks, documents, members, invites, and settings). Confirming requires typing `DELETE GUILD <NAME>` (the whole phrase uppercased) and re-entering your password; OIDC-only accounts, which have no password, are asked only for the phrase.
- **Active Guild highlight.** The active guild is now highlighted by a more subtle bottom pill when on a home page (My Tasks, My Documents, etc), to reduce confusion on where you are in the app.

## [0.46.2] - 2026-05-27

### Added

- **Counter `+`/`−` button feedback.** Each press fires a short audio tick (`tick.wav` on increment, `tick_reverse.wav` on decrement) and a brief haptic tap. Works on both the row/grid cards and the focus view. No user preference gating yet.

### Changed

- **Counter `+`/`−` buttons disable at their bounds.** When a counter is at its configured `max`, the `+` button is disabled; at `min`, the `−` button is disabled. Applies to both the row/grid cards and the focus view. Counters without a configured bound (`null` min/max) are unaffected.
- **Counter `+`/`−` buttons tap more reliably on mobile.** Added `touch-action: manipulation` to the step buttons so a slight finger wobble during a press no longer cancels the click as a swipe, and the synthetic-click delay is gone.
- Removed email from the app sidebar to protect user privacy.

## [0.46.1] - 2026-05-24

### Added

- **Counter focus view.** Each counter can now be opened in a full-screen, mobile-first layout via the "Open full screen" menu item on the row (URL: `/g/{guildId}/counter-groups/{groupId}/counter/{counterId}`). The view scales the value, progress bar, or segmented-clock dial to fill the viewport, exposes thumb-zone-sized `−`/`+` controls in the bottom safe area, lets you cycle through the group's counters with chevrons or a horizontal swipe, and stays in sync with other clients via the existing WebSocket. Counter view components gained a `2xl` size variant used by this layout.

### Changed

- **Filter and view-mode preferences are now per-user, not per-device.** Project task filters (assignee, tag, status, due, property, show-archived, view mode), the Projects / Documents / My Tasks / Created Tasks / My Documents / My Projects / My Calendar filter sets and sort orders, and the counter group row/grid layout toggle now persist to a new `user_view_preferences` table keyed by `(user_id, scope_key)` instead of `localStorage`. Set filters once and they apply on every device you sign in to. A one-shot migration on first authenticated load uploads any legacy `localStorage` values to the server and clears them locally. Sidebar collapse states, side-panel state, and similar device-specific UI prefs still live in local storage.

## [0.46.0] - 2026-05-23

### Added

- **Recent items bar now spans more than projects.** The sticky tabs strip at the top of the app surfaces the 20 most recently opened guild-scoped items across projects, documents, queues, and counter groups, ordered by last viewed. Each tab shows an entity-specific icon (project emoji, file-type icon for documents, `GalleryHorizontalEnd` for queues, `Gauge` for counter groups) and links to the matching detail page. The previous projects-only `/projects/recent` endpoint has been replaced by a polymorphic `recent_views` table and a single `GET /api/v1/recents` endpoint; new `POST /<entity>/{id}/view` and `DELETE /<entity>/{id}/view` endpoints record/clear views for each of the four entity types.
- **Command center expanded.** The Suggested group now lists the top 5 mixed recents (projects, documents, queues, counter groups) instead of projects only, and dedicated Queues and Counter Groups sections were added so they participate in fuzzy search the same way Projects and Documents do. The Tasks group defaults to the 25 most recently updated tasks assigned to you (skipping done) — so you see what you're actively working on instead of the top of every project's kanban. The Documents group likewise defaults to the 25 most recently updated documents in the active guild. Typing in the input now performs a guild-wide title search against the backend for both tasks and documents, so any item is reachable from the command center regardless of whether it's in the default list.
- **Global "Add Document" action.** Mirroring the existing global Add Task wizard, a new guild-then-initiative picker is reachable from the command center's Actions group and from a new "New document" button in the My Documents page header. The wizard auto-advances when there's only one guild / initiative, persists a "last used" shortcut for one-click access, and hands off to the existing Documents page (`?create=true&initiativeId=…`) so the actual creation UI is unchanged.

## [0.45.1] - 2026-05-22

### Added

- **Hold your turn (queues).** A new Hold button on the queue toolbar pauses the current turn — the held participant leaves the rotation, and Next advances to whoever's up next. Held items appear in a dedicated "Held" section above the rotation in the On Deck view, each with an "Act" button. Clicking Act opens a small menu with two options: **Act in place** keeps them at their original queue position so they re-enter at their natural slot when the rotation reaches it again, while **Act and reposition** rewrites their initiative to land just above the current turn and makes them the current turn — PF2e Delay semantics, where the new slot persists for the rest of the encounter. If they never act, the rotation auto-restores them at their natural slot the next time it comes around — so a held player can't be silently forgotten. Held state is recorded with the round the hold happened in (`held_at_round`), so the auto-release logic knows when their slot is "due back."
- **"On Deck" view for queues.** A new view mode on the queue detail page renders upcoming turns as a vertical sequence: the current turn sits at the top, the next item rises into the top slot on Next, and the previous current turn rolls down to its place in the next round behind a round separator. The separator stays anchored across turns (it morphs into position rather than popping in and out, so the round-boundary transition animates smoothly) and its label crossfades when the round number changes. Stopping the queue resorts the rows back to default (position-desc) order and clears the current-turn highlight. Animations are driven off the cached queue data, so they play uniformly for the local user's turn clicks, the matching server response, *and* WebSocket-driven refetches when another participant advances the queue — via the View Transitions API (with a graceful fallback for older browsers and `prefers-reduced-motion`). Hidden items appear below a "Hidden" divider so they remain editable from the same view without taking a turn. "On Deck" is the default view; the choice (list or on-deck) is remembered per queue.
- **Sort all counters in a group at once.** A "Sort" dropdown on the counter group toolbar reorders every counter by name (A→Z / Z→A) or current count (low→high / high→low). The sort persists by reassigning each counter's position on the backend and broadcasts over WebSocket so other viewers update live; manual drag-and-drop reordering still works afterward.
- **Duplicate a counter group.** A "Duplicate" action in the counter group settings (Advanced tab) creates a copy with all of its counters and their current values, bounds, view modes, and order. The copy keeps the source group's role and user permissions and makes you the owner; you can name the copy or accept the default "(Copy)" suffix.

### Changed

- **Queue item positions are now fractional.** `queue_items.position` is stored as `Numeric(20,10)` instead of an integer, so items sharing the same initiative value can be ordered with finer granularity (e.g. dropping an item at `10.5` between two items at `10` without renumbering them), matching the fractional-position indexing already used by Counters.
- **Queue turn controls feel instant.** Start, stop, next, previous, reset, and set-active now update the displayed current item and round optimistically instead of waiting for the API round trip, then reconcile with the server (and the queue WebSocket) once it responds. A failed request rolls the change back.

## [0.45.0] - 2026-05-22

### Added

- **Counters advanced tool for initiatives.** A new initiative-scoped feature for tracking numeric values like HP, ammo, scores, or budgets. Data model is `Initiative > Counter Group > Counter`, mirroring Queues with full DAC (user + role permissions), guild-scoped RLS, soft-delete, and real-time WebSocket updates. Each counter has its own `count`, `min`/`max` bounds, `step`, `initial_count`, and view mode (`number`, `progress_bar`, or `segmented_clock`). Counts can be set directly, incremented/decremented by step, or reset to the initial value; a "Reset All" button on the group resets every counter at once. Counters use fractional-position indexing (`Numeric(20,10)`) for single-PATCH drag-and-drop reordering within a group. Adds the `counters_enabled` initiative master switch and `counters_enabled` / `create_counters` per-role permission keys (backfilled: managers ON, members OFF). New routes: `/counter-groups`, `/counter-groups/:groupId`, `/counter-groups/:groupId/settings`.

### Fixed

- **Spreadsheet column/row resize now persists on Mac (and other high-DPI/Retina devices).** Pointer events on Retina displays report fractional coordinates (e.g. `clientX = 123.5`), which the spreadsheet's `clampInt` integer validator rejected. The sanitized formatting record then came back empty, and `updateColumn` / `updateRow` interpreted that as "delete the entry" — so releasing the mouse silently reverted the column or row to its default size. The resize handler now rounds the new size to an integer before committing. Also rewrote the resize event wiring to attach `pointermove` / `pointerup` / `pointercancel` listeners synchronously inside `pointerdown` (eliminating a latent race where a fast release on a Mac trackpad could miss `pointerup` before the React effect attached).

- **Pagination control now resyncs when external code resets the page.** When a filter change called `setPage(1)` on the My Tasks / My Projects / My Documents / Created Tasks / Documents / Tag Tasks tables, the underlying query refetched page 1 correctly but the DataTable's internal pagination control kept its old `pageIndex`, so the UI continued to show the previous page number and an empty/short data page. DataTable now accepts a controlled `pageIndex` prop in `manualPagination` mode and syncs to it on change. Bug existed since manual pagination was introduced; surfaced while validating filter behavior in the Biome migration.

### Changed

- **Frontend tooling: migrated from ESLint + Prettier to Biome.**

## [0.44.3] - 2026-05-18

### Fixed

- **iOS/Android native app: content no longer renders behind the status bar.** All viewport-level sticky headers and sidebars now absorb the safe area inset at the top, so controls appear below the status bar on devices with a Dynamic Island or notch. The fix covers the main app header, the guild icon column, both sidebar headers (home and guild views), the document side panel, and the activity sidebar. The home indicator safe area is also applied at the bottom on native iOS.
- **Native iOS app could not connect when `CORS_ALLOWED_ORIGINS` was restricted (follow-up to v0.44.2).** Capacitor's iOS WebView uses `capacitor://` as the default URL scheme, producing the origin `capacitor://com.morelitea.initiative` — distinct from the `https://` origin Android sends. This origin was not included in the automatic native-origins allowlist, so iPhones were still rejected. The backend now allows `capacitor://com.morelitea.initiative` in addition to `https://com.morelitea.initiative`. The Capacitor config also adds `iosScheme: "https"` so future iOS builds use the same `https://` origin as Android, making a single origin sufficient going forward.

## [0.44.2] - 2026-05-17

### Fixed

- **Native iOS/Android app could not connect when `CORS_ALLOWED_ORIGINS` was restricted.** Capacitor native apps send requests from `https://com.morelitea.initiative`, which was not included when operators set a specific origin allowlist. The backend now automatically appends the Capacitor native origins to any non-wildcard `CORS_ALLOWED_ORIGINS` list, so the mobile app works without requiring manual configuration.

## [0.44.1] - 2026-05-17

### Fixed

- **HTML and SVG documents now preview in the in-app viewer.** The `X-Frame-Options: DENY` header added in 0.44.0 also applied to the document-download endpoint, so the file viewer's iframe was blocked from displaying uploaded HTML/SVG files (`refused to display … X-Frame-Options to 'deny'`). The inline document response now sends `X-Frame-Options: SAMEORIGIN` and `Content-Security-Policy: frame-ancestors 'self'`, so the same-origin viewer can render them while cross-origin framing stays blocked. The existing `script-src 'none'` and sandboxed iframe are unchanged — uploaded HTML still cannot execute scripts, so there is no stored-XSS regression.

## [0.44.0] - 2026-05-16

### Added

- **Spreadsheet undo/redo (per session).** Spreadsheets now support undo/redo via toolbar buttons and keyboard shortcuts (Ctrl/Cmd+Z, Ctrl+Y / Cmd+Shift+Z), covering cell edits, paste, formatting, borders, column/row resize, freeze, and CSV/XLSX import. History is per user and per session and works whether collaboration is on or off; a peer's edits are never undone by you. Built on a new editor-agnostic `useYjsHistory` primitive (wrapping `Y.UndoManager`) that any future Yjs-backed editor can reuse with a small adapter.
- **Spreadsheet formatting and Excel import/export.** Spreadsheet documents now support column widths and row heights (drag the header edges; double-click to reset), number formats (currency, percent, date, fixed decimals, adjustable decimal places, thousands separator, and negative styles including red and parentheses), frozen header rows/columns, text/fill styling (bold, italic, underline, strikethrough, font size, text color, background fill, horizontal and vertical alignment), and per-edge cell borders (thin/medium/thick/dashed/dotted/double, any color, with all/outer/side presets). Formatting applies to the current selection — a cell range, or whole columns/rows selected from the headers — via a responsive formatting toolbar (related controls grouped into popovers on desktop, collapsed into a single overflow panel on small screens; file import/export lives in a compact menu), and syncs in real time to collaborators. A new "Export Excel" action produces a styled `.xlsx`, and the import button now accepts `.xlsx` alongside CSV, preserving widths, styles, number formats, borders, and frozen panes on round-trip (CSV import/export is unchanged). Existing spreadsheets upgrade transparently on next save (content schema v1 → v2) — no migration or operator action required.

### Security

- **Auto-sanitize HTML on all API inputs.** Every Pydantic schema now extends `SanitizedBaseModel`, which runs `nh3.clean()` on every `str` field at validation time. Dangerous markup — `<script>`, `<iframe>`, `on*` event-handler attributes, `javascript:` URLs — is stripped before reaching services or the database. Safe formatting tags (`<b>`, `<i>`, `<a>`, `<p>`) pass through unchanged, and fields that must preserve user-authored content (descriptions, comments, document content, queue notes) opt out via the explicit `RichTextStr` type. Enum-typed fields are skipped automatically.
- Limit image attachment uploads to 10 MB to prevent memory exhaustion
- Block OIDC new-account creation when `ENABLE_PUBLIC_REGISTRATION` is disabled
- Return opaque error codes from import parse endpoints instead of raw exception text
- Add 5-minute TTL to OIDC discovery metadata cache
- Add `X-Content-Type-Options`, `X-Frame-Options`, and `Referrer-Policy` headers to all responses
- Guard AI settings `base_url` against SSRF — validates against private/loopback/link-local IPs at both request time and write time for ollama and custom providers
- Add `CORS_ALLOWED_ORIGINS` config variable to replace the `allow_origins=["*"]` placeholder
- **Stored XSS in legacy document embed nodes.** The Lexical `EmbedNode` (kept around for backwards compatibility with documents that used the old generic embed type before `YouTubeNode` / `TweetNode` existed) rendered its stored `html` field via `dangerouslySetInnerHTML` without sanitization. A user able to write a document — i.e. any guild member with edit access — could craft a serialized JSON payload containing `{ "type": "embed", "html": "<script>…</script>" }`, save the document, and have the script run in every other viewer's session. The constructor now passes the html through DOMPurify before storing it on `__html`, so all entry paths (importJSON of legacy data, paste-conversion via `convertEmbedElement`, programmatic creation) are sanitized at the same boundary. Default DOMPurify config strips `<script>`, event handler attributes, `javascript:` URLs, and `<iframe>`; legacy YouTube embeds may render empty after the fix and should be re-added with the dedicated `YouTubeNode` insert tool.
- **Migrate password hashing from passlib[bcrypt] to argon2-cffi.** passlib's last release was Oct 2020; its bcrypt backend has been emitting `(trapped) error reading bcrypt version` ever since bcrypt 4.1 removed the `__about__` module, and the project's `bcrypt==4.0.1` pin existed only to keep passlib quiet. New password hashes are now argon2id (OWASP-aligned defaults), and existing bcrypt hashes are still verified directly through the `bcrypt` library so nobody is locked out. On the next successful login (standard form auth or device-token auth) any bcrypt hash is rewritten as argon2id transparently — no schema change, no migration, no operator action required. bcrypt itself bumps from 4.0.1 to 5.0.0 along the way, since the version pin was only there to dodge the passlib incompatibility.

### Changed

- Restrict Ollama AI provider to platform-level settings. Guild and user AI settings no longer offer Ollama as a provider option (it cannot reasonably be reached from outside the host's network anyway). A migration nulls out any pre-existing Ollama overrides on guild_settings and users, falling back to the inherited platform configuration.
- Show an inline HTTP warning on the platform AI page when the Ollama base URL is configured with `http://`, reminding admins to use TLS in production.
- Platform admins can now point Ollama / custom AI base URLs at `http://` or private addresses. The SSRF guard still applies to guild/user-supplied URLs in the test-connection and fetch-models endpoints; it is bypassed only when the caller is a platform admin (who already controls the host). AI generation paths trust ollama URLs unconditionally now that ollama is platform-only.
- Bump vite from v7 to v8. Decreases bundler step from 25s to 2s.
- Migrate to typescript 7 beta. Decreases compile step from 25s to 5s.
- Bump Dockerfile Node.js from v20 to v24.
- Pin pnpm to 10.33.3 via the `packageManager` field in `frontend/package.json`. CI and the Dockerfile auto-detect it through corepack, so contributors no longer need to match versions manually — fresh clones with corepack enabled get the right pnpm on first invocation.

## [0.43.2] - 2026-05-03

### Added

- **Optional captcha gate on registration.** Set `CAPTCHA_PROVIDER` (one of `hcaptcha`, `turnstile`, or `recaptcha` — v2 only for reCAPTCHA, since the gate uses the rendered checkbox widget rather than v3's score flow), `CAPTCHA_SITE_KEY`, and `CAPTCHA_SECRET_KEY` and the public registration endpoint will require a solved widget before creating an account. The SPA picks the right widget at runtime based on `GET /api/v1/config`. Bootstrap-first-user registrations (no users yet) and the OSS default (no env vars set) are silently skipped — registrations work exactly as before. The verifier fails closed on provider network errors, so a transient outage rejects registrations rather than letting them through unchecked.

### Changed

- **Auto-detect timezone on registration.** The register form now forwards the browser's resolved IANA timezone (`Intl.DateTimeFormat().resolvedOptions().timeZone`) so a new account's wall clock matches where the user actually is, instead of starting at the model default of `"UTC"`. Time-of-day features (rolling recurrence, due-date display, daily digests) read the stored zone, so the new default removes a step from the "why is my task scheduled at 5 AM?" loop. Non-SPA callers (curl, integration scripts) that omit the field still get the `"UTC"` default — no breaking change. OIDC sign-in still picks `"UTC"` until the user updates it in settings; that flow has no SPA form to attach the value to.

- **Timezone editor on the Profile tab.** Settings → Profile now exposes the same timezone picker that's been on Settings → Notifications, so a wrong default surfaces and is fixable on the first profile pass instead of requiring users to find the notifications tab. The picker, fallback list, and `Intl.supportedValuesOf("timeZone")` resolution moved to a shared `lib/timezones.ts` so both pages stay in sync.

### Fixed

- **Rolling recurrence off-by-one across the UTC date boundary.** A task set to repeat "every N days after completion" anchored its next due date on the UTC calendar day, not the user's local one. For tasks whose local time crossed midnight UTC (e.g. 5pm Los Angeles is 00:00 UTC the next day), completing the task one local day earlier than the UTC day produced a next occurrence one day too soon — `every 3 days` ended up scheduling 2 days out. The advance step now converts both `now` and the original due time into the user's stored timezone before doing the date math, so the new occurrence lands on the user-intuitive calendar day.

- **Settings unreachable when you have no guild memberships.** A user with zero memberships used to see only the "no guild" screen with create/join/logout — no path to user settings (so no way to delete their own account) and no path to platform-admin settings either. The empty-state screen now exposes **Account settings** (always) and **Platform settings** (when `user.role === "admin"`) buttons, and the `/profile/*` and `/settings/admin/*` routes render in a minimal Back-to-start shell instead of bouncing back to the empty state.

## [0.43.1] - 2026-05-02

### Changed

- **Self-deactivation / deletion UX.** Settings → Danger Zone now exposes **Deactivate Account** and **Delete Account** as two separate buttons next to their descriptions, instead of a single ambiguous opener that landed on a radio chooser. Each button takes you straight to the eligibility check for that action, the dialog title and step descriptions match the action you picked, and the deactivate copy now spells out that you'll be removed from every guild you're in (rejoining requires a fresh invite).

### Fixed

- **Orphaned projects when leaving a guild.** Leaving a guild while owning projects in it would silently strand the rows: the user's initiative membership got dropped, no DAC permission survived, and guild admins (who have no implicit project bypass) couldn't reach them. Leaving now forces a per-project decision — for each project you own in the guild, the dialog asks whether to transfer ownership to a project manager or delete the project (which sends it to the guild's trash retention bucket). The transfer-recipient picker is filtered to initiative managers since they're the role that actually administers projects. The eligibility endpoint surfaces the project list so the SPA can pre-flight the prompt, and the backend rejects a leave whose disposition map doesn't cover every owned project exactly once. The OIDC group-sync removal path, which has no UI to ask, auto-transfers ownership to an active initiative manager (falling back to a guild admin) before dropping the user, and logs a warning when neither exists.

- **Orphaned projects when a guild admin removes a member.** The user-management table's "Remove from guild" button shared the same orphan hazard as self-leave: the backend just dropped initiative memberships and walked away. The remove dialog now pre-flights `GET /users/{user_id}/guild-removal-eligibility` and renders a per-project radio (transfer to a project manager, or delete) so the admin always has an escape hatch — including for projects in initiatives where no other PM is available. The eligibility response bundles candidate transfer recipients per-project, so the picker works even for initiatives the admin doesn't belong to.

- **Project access dropdown blank for a reactivated former owner.** If a project owner self-deactivated (which forced an ownership transfer to another member) and was later reactivated and re-added to the initiative, the project's individual-access list showed them at the old `level=owner` but the access dropdown was blank because two users now had owner-level rows pointing at the same project. `transfer_project_ownership` now drops the departing owner's `ProjectPermission` row as part of the transfer — every call site is a "user is leaving" path so the row was already stale.

- **Wrong password on the deactivate / delete form signed you out.** The self-deletion endpoint returned `401 UNAUTHORIZED` for a password mismatch, which the SPA's global axios interceptor treats as a session-expiry signal and force-logs-out from. The user was kicked back to the login screen instead of seeing "wrong password" inline. The endpoint now returns `400` for that specific case (the user _is_ authenticated — they just typed the wrong confirmation password), so the error stays scoped to the form.

- **Error toasts no longer leak raw backend codes.** A class of `toast.error(...)` call sites was passing through the raw `error.message` or `response.data.detail` string as a fallback, which surfaced backend constants like `USER_INVALID_PASSWORD` to users when there was no client-side mapping. All of those now route through the existing `getErrorMessage(error, "namespace:fallbackKey")` helper, which looks up the code in the `errors` translation namespace before falling through to a localized fallback. The `errors` namespace is also now preloaded with `common` so the lookup works on any page (previously, only pages whose `useTranslation` happened to include `errors` resolved codes correctly).

## [0.43.0] - 2026-05-01

### Added

- **Spreadsheet documents.** Pick **Spreadsheet** from the document-type dropdown when creating a new document to get a virtualized cell grid that scrolls horizontally and vertically without bound. Edit cells with click + type / Enter / Tab / arrow keys; copy and paste between cells (and from Numbers / Excel / Sheets — multi-row / multi-column blocks expand into the grid). Toolbar buttons export the sheet as CSV or import a CSV file. Cells store strings, numbers, booleans, or blanks; numeric- and boolean-looking inputs get auto-coerced to the right type, and booleans render as interactive checkboxes. Edits sync in real time between users on the same document over the existing yjs collaboration infrastructure, and each user's currently-selected cell shows up to peers as a colored ring with their name.

- **Webhook subscriptions for the advanced-tool service.** Outbound HMAC-signed event delivery (sha256 over `timestamp + "." + body`) so the embed can react to writes (e.g. `task.created`) without polling. Subscriptions are guild-scoped, RLS-protected, and the HMAC secret is returned only at create time. _Note: likely temporary scaffolding for testing the embed integration; expect the contract to shift as it shakes out._

- **Delegation auth for the advanced-tool service.** Accept short-lived RS256-signed JWTs from the embed's backend so it can call Initiative on a user's behalf. Existing RLS + role-permission checks still gate every action — delegation answers only "who is acting." Deactivated users can't be impersonated. Disabled by default; opt in with `AUTO_DELEGATION_PUBLIC_KEY_PEM`.

- **Embedded advanced tool integration.** Initiative now supports plugging in an externally-deployed companion app as an iframe panel under specific initiatives or as a dedicated guild settings tab. Operators set `ADVANCED_TOOL_NAME` and `ADVANCED_TOOL_URL` on the backend; without those, the entire feature stays fully hidden — no UI surface, no per-initiative toggle, and the API endpoints return 404.
  - **Per-initiative panel** — initiative managers turn it on under Initiative settings → Details → Advanced Tools. Once enabled, the panel becomes the first item in the initiative's sidebar group for any user whose role grants the new `advanced_tool_enabled` permission.
  - **Per-guild panel** — guild admins get a dedicated tab in guild settings for cross-initiative or admin-only views. The tab only appears when the deployment has an advanced tool URL configured AND the user is a guild admin.
  - **Role-based access control** — two new initiative-level permission keys (`advanced_tool_enabled`, `create_advanced_tool`) gate visibility and creation rights at the role level. Built-in managers get both by default; members get neither.
  - **Security model** — embedding uses a 60-second audience-scoped JWT delivered to the iframe via postMessage (never the URL). Strict origin checks on every postMessage; iframe is sandboxed (`allow-scripts allow-same-origin allow-forms allow-downloads`); locale forwarded so the embed picks up the user's language without re-prompting. JWT can be signed with RS256 via `HANDOFF_SIGNING_PRIVATE_KEY_PEM` so the embed verifies with a public key only — no shared secret. Falls back to HS256 with `SECRET_KEY` for OSS deployments. Tokens carry a `jti` so the embed can refuse repeat redemption within the validity window. The handoff endpoint authorizes membership + role + master-switch + URL-configured before issuing a token, so the embed never has to make access decisions on its own.
  - **Runtime config endpoint** — `GET /api/v1/config` exposes the deployment's advanced-tool config (URL + name) so the SPA discovers it at boot without rebuilding the bundle.

- **Project export & import.** Settings → Advanced now offers an **Export as JSON** button that downloads a self-contained JSON file with the project's metadata, task statuses, project tags, tasks (with subtasks, recurrence, priorities, dates, and custom property values), and the property _definitions_ those tasks reference. From the projects page, an **Import** button next to **New project** accepts a JSON export and recreates the project under any initiative you can create projects in — including across separate Initiative installations. References are name- and email-based so IDs from one database don't leak into another:
  - **Tags** are matched against the target guild by name; new tags are created if they don't exist.
  - **Task statuses** are recreated per-project from the export.
  - **Custom properties** are matched by name in the target initiative. If the target already has a property with the same name but a different type, the imported one is renamed `<name>_<type>` (e.g. `Severity_select`) so the existing property is never mutated.
  - **Assignees** are matched by email against the target initiative's members. Unmatched emails are reported in a toast warning and silently dropped — the importer becomes the project owner and `created_by` for every task.
  - The format is **versioned** (`schema_version`) so future format changes can refuse stale exports cleanly.

- **Trash and Restore.** Deleting a project, task, document, comment, initiative, tag, queue, queue item, or calendar event now sends it to a trash can instead of permanently destroying it. Items stay there for the guild's retention period (default 90 days; admins can change it under **Settings → Guild → Trash retention** or set "Never" to keep things forever).
  - **Personal view** — every member sees a **Trash** tab under their profile listing the things they deleted, with a **Restore** button next to each.
  - **Guild view** — guild admins also get a **Trash** tab under **Settings → Trash** that shows everything trashed in the guild plus an admin-only **Delete now** button for permanently purging an item before its retention timer is up.
  - **Restore handles missing owners** — if you trashed a task and the owner has since left the initiative, restore opens a picker so you can hand ownership to someone else before bringing the row back.
  - **Cascades preserved** — trashing a project hides its tasks too; restoring it brings them back together. The trash listing only shows the parent so you don't get drowned in 200 cascaded rows.
  - **Auto-purge** runs hourly so expired items leave on their own.
  - The Postgres layer now refuses raw `DELETE` from the application role on every soft-delete-capable table, so a stray query can't accidentally bypass the trash flow.

- Export users as CSV from **Settings → Users** (guild admins) and **Settings → Admin → Users** (platform admins). Each row gets an **Export** button, and the card header has **Export all as CSV**. Exports include ID, email, full name, role, status, and initiative roles — enough for HR or compliance teams to keep an offline record before an account is removed.

- **Chester the Mimic** — a pixel-art treasure chest mascot now greets you in toast notifications. Each toast type pairs with a Chester mood (success → proud sparkles, error → chomping, warning → thinking, info → talking, default → idle), and the seven mood SVGs ship as standalone animated assets. Platform admins can preview them all from the new "Chester toast playground" card in **Settings → Admin → Branding**.

- **Keep screen awake.** A new toggle under **Settings → Interface** prevents this device's screen from dimming or locking while the app is open. Useful for long planning or reading sessions on a tablet at the table. The setting is per-device — it's saved locally (localStorage on web, Capacitor Preferences on native) and never synced to the backend, so each device can opt in independently. Uses the Screen Wake Lock API on web and the native idle-timer/`FLAG_KEEP_SCREEN_ON` flag on Capacitor builds.

### Changed

- **Account deletion now has three options instead of one.**
  - **Deactivate** (new) — your account is locked but kept intact. An admin can reactivate it later. Pick this if you might come back.
  - **Delete my account** (replaces the previous "soft delete") — your name, email, avatar, and login are wiped. The account row stays so the comments, tasks, and documents you authored remain visible (attributed to "Deleted user #{id}") instead of vanishing from your team's history. This is permanent.
  - **Hard delete** (admin only) — completely removes the row and everything attributed to it. Hidden from the user-facing dialog; only platform admins can do this from the admin page.

  All account-deletion paths now require you to transfer ownership of any projects you manage before submitting, so projects always have an active owner.

- The platform users page status column shows **Active**, **Deactivated**, or **Anonymized** in place of the old Active/Inactive label, and the "Reactivate" button is hidden for anonymized accounts (their data is gone — there's nothing to bring back).

- Anywhere a deleted user used to appear (comment authors, task assignees, mentions, calendar attendees, document collaborators), they now show as **Deleted user #{id}** with a neutral avatar instead of a stale name or email.

- Anonymized users are filtered out of "add member" and @-mention pickers, so you can't accidentally assign or mention someone whose account no longer exists.

- **Single Docker image for OSS and hosted deployments.** The dual-build setup (separate `*-infra` image with `INSTALL_INFRA_EXTRAS=true`) is gone — one image now serves every deployment, with the advanced tool integration enabled at runtime via env vars instead of at build time. The `INSTALL_INFRA_EXTRAS` build arg, the `requirements-infra.txt` extras file, and the `build-docker-infra` GitHub Actions job have been removed. Self-hosters get the same image we run; auditors can verify by inspection that the public image has no automation/event-publishing code paths.

- Bump lexical dependencies for a more stable document editor.

- Migrated the document editor to Lexical 0.44's Extension API. No user-visible behavior change, but the editor now uses `LexicalExtensionComposer` with `defineExtension` instead of the legacy `LexicalComposer` + plugin-list pattern, which clears the deprecation warning around `CodeNode` and aligns the editor with the upstream shadcn-editor architecture so future Lexical updates are easier to absorb.

### Fixed

- Read-only members can now create new documents from a template they have access to. Previously the copy required write access to the template, which defeated the point of templates being shared starters. Copying a non-template document still requires write access on the source.

- Deleting a document from the document settings page no longer fires two success toasts.

- Drag-scrolling a kanban board no longer smears a text selection across every card the pointer passes over.

- The document markdown converter now round-trips paragraph structure correctly. Toggling **Convert from markdown** previously turned a `\n\n` paragraph break into two stacked soft line breaks; converting back then re-emitted single newlines, so paragraphs steadily collapsed each time you toggled. Paragraph breaks now serialize as `\n\n` in markdown and parse back as real paragraphs, and shift+return soft breaks survive the round trip via the standard CommonMark hard-break syntax.

- The guild filter on **My Tasks** and **Created Tasks** silently ignored your selection — picking one or more guilds still showed tasks from every guild you belong to. The pages now narrow correctly.

- Documents owned by a departing user no longer become orphaned when the user leaves the initiative — whether they leave the guild, deactivate or delete their own account, get removed by an admin, or get unassigned via OIDC sync. The initiative's project managers automatically inherit ownership of those documents, so anyone who needs to find or clean up old work after a team move still can.

- Custom properties UI is now translated to Spanish and French. Previously, users on those locales saw English labels throughout the properties picker, manager, and filters.

### Removed

- **Automation engine, event publisher, and `aioboto3` dependency.** Domain-event fan-out for automation now lives entirely in the separately-deployed advanced tool service rather than in the FOSS backend. The bundled Kinesis publisher, the in-process automation engine, the Redis dependency, and the `automations_enabled` initiative flag (replaced by the generic `advanced_tool_enabled` slot) are all gone from the FOSS image. Fresh installs are unaffected; existing databases get a clean migration path.

## [0.42.1] - 2026-04-28

### Fixed

- The task edit page sometimes opened with the wrong status, priority, and recurrence shown until you nudged the page (added a tag, changed a property, etc.), then it would suddenly snap to the right values. All three fields now read from the task's own data on the first render instead of waiting for a delayed copy into local form state, so the form is correct the moment the task loads.

## [0.42.0] - 2026-04-23

### Added

- **Custom properties** on documents, tasks, and calendar events. Initiative managers define reusable properties from a new Custom Properties tab in initiative settings, picking from nine types (text, number, checkbox, date, date & time, URL, single-select, multi-select, or person). Attach them to any document, task, or event alongside tags; filter by them in every list; toggle per-property columns on the task and document tables; and see compact chips on kanban cards, document cards, and the calendar list view. Select/multi-select pickers support creating new options inline without leaving the entity.

### Removed

- Moving a project between initiatives. The "Initiative ownership" card is gone from project settings and `PATCH /projects/{id}` no longer accepts `initiative_id`. The move crossed a privacy boundary — the project and everything attached to it suddenly became visible to a different initiative's members — and each new initiative-scoped attachment (role permissions, tags, custom properties, calendar events) needed its own cascade rule to stay coherent. The cost of keeping the move correct grew faster than the demand for the feature. Create the project in the right initiative from the start; if you end up in the wrong one, duplicate it into the target and delete the original. A follow up will enable export and import for projects that will cover this use case.

### Changed

- Avatars are now consistent everywhere a person appears. The same deterministic color that powers the whiteboard cursor and Lexical editor caret tints the initials fallback in comments, task assignees, queue item owners, @-mention typeahead, calendar attendees, custom-property people pickers, and the collaboration badge. The collaboration badge and custom-property people cells also show uploaded profile pictures when available; previously both only ever showed initials. Non-user avatars like guild icons are unchanged.

## [0.41.0] - 2026-04-21

### Added

- New **smart link** document type. Create one from the dialog's new third tab by pasting a URL — Figma files, YouTube videos, Loom recordings, Vimeo videos, Google Docs/Sheets/Slides/Drawings, Miro boards, Airtable embed views, and Office docs are embedded inline; other URLs render a link card that opens in a new tab. Only the URL is stored; Initiative doesn't fetch anything from the link. Adding support for a new provider later automatically upgrades any existing smart-link docs whose URLs match that provider — no migration needed, since the provider is always derived from the URL at render time.
- Multiplayer cursors on whiteboards. When multiple users edit the same whiteboard document at once, each person now sees the others' pointer positions in real time, labeled with their name and tinted with their avatar color. Cursor updates piggyback on the existing Yjs awareness channel, so no new backend routes were needed.

### Changed

- Collaboration cursor colors are now deterministic per user and consistent across the app. The Lexical document editor caret, whiteboard cursor, and collaboration badge avatar all derive the same color from the user's id, so a given user shows up the same way everywhere. Previously the Lexical caret picked a random color per session and the avatar badge used a separate palette, so none of them agreed.

## [0.40.0] - 2026-04-20

### Added

- Optional Task Completion Visual Feedback effect when you mark a task you're assigned to as Done. Choose from None (default), Confetti, +1 Heart, Natural 20 d20 roll, Gold Coins, or Random (surprise me) under user settings → Interface. All effects use a unified 8-bit pixel-art aesthetic.
- Sound and haptic siblings to the task completion feedback. The new "Sound on task completion" and "Vibration on task completion" toggles in user settings → Interface play a short pop and trigger a two-pulse vibration (where supported) when you mark **any** task done — not just one assigned to you, since these are subtle enough to fire on every closeout. Both default to on; existing users get them enabled automatically. Haptics use the Capacitor Haptics plugin on native iOS/Android and fall back to the Web Vibration API in browsers that support it.

## [0.39.1] - 2026-04-18

### Added

- Fullscreen toggle in the document and whiteboard editors. The editor, its toolbars, action bar, and collaboration status take over the window for distraction-free writing or large-canvas diagramming. The Fullscreen button sits inline with the collaboration status badge above the editor.

### Fixed

- "Not tagged" filter in the Documents page tag tree view now actually filters to untagged documents. The page was computing the selection state but never sending the `untagged` query parameter to the backend, so selecting "Not tagged" returned every document instead of only the untagged ones.
- Leaving a collaborative document now tears the connection down cleanly. Other collaborators no longer see the leaver's avatar flicker (disappear briefly then reappear), and the "Collaboration connection failed — Maximum reconnection attempts reached" toast no longer fires after the user has navigated away from the document. The unmount cleanup in `useCollaboration` was using a soft, debounced `disconnect()` (a React Strict Mode optimization) instead of `destroy()`, leaving the provider alive in the global pool, the reconnect loop running, and the error callback still wired to the unmounted page's toast.

## [0.39.0] - 2026-04-14

### Added

- Improved task status UX: each status now has a customizable color and icon, with smart defaults driven by its category (backlog, todo, in progress, done). Kanban column headers show the status icon and a colored accent bar, and every status dropdown (kanban, project table/gantt rows, My Tasks, tag task lists, task edit page) now shows the icon beside the name and mirrors the active status color on the trigger border.

### Fixed

- Auto-redirect to the welcome/login page when the access token expires, instead of leaving the app in a broken state until the user manually refreshes. Shows a "Your session has expired" toast before the redirect.
  - Backend now returns `401 Unauthorized` (with `WWW-Authenticate`) for expired or invalid JWTs, invalid device tokens, and malformed token payloads, rather than `403 Forbidden`. Genuine authorization failures are unchanged.
  - Frontend 401 interceptor no longer silently swallows expired-session 401s on web cookie auth: an explicit session flag tracks whether a user is currently signed in, regardless of whether the in-memory bearer token was ever populated.
- Fix manual logout so previously-issued JWTs are actually invalidated server-side. The logout endpoint was using `AdminSessionDep` while `get_current_user_optional` used `SessionDep`, so in production the `current_user` object came from a detached session and the `token_version += 1` bump was silently dropped on commit. Previously-signed JWTs (and any still-cached HttpOnly cookie) stayed valid until natural expiry, letting users navigate back into protected pages by typing the URL after clicking "Sign out". The endpoint now uses a single `SessionDep` so FastAPI's per-request dependency cache hands both sites the same session, and the commit actually persists.

## [0.38.1] - 2026-04-12

### Fixed

- Fix whiteboard persistence losing edits on refresh / navigation
  - Add localStorage write-ahead cache so unsaved scenes survive page unload regardless of keepalive PATCH timing
  - Gate WhiteboardDocumentEditor on scene-ready state so Excalidraw's `initialData` captures the correct scene instead of the empty `useState` default
  - Skip stale Yjs initial sync in observer — only apply live updates from other users after bootstrap
  - Only clear `yjs_state` on PATCH when no active collaborators are in the room, preventing a data-loss window during periodic content-sync
  - Guard the document load effect so PATCH responses don't reset the live whiteboard scene mid-edit
- Fix whiteboard cache poisoning when rejoining a live room — a user rejoining with a stale local cache no longer clobbers the live room's state. The bootstrap now applies the Y.Map state whenever other collaborators are present, and local edits are gated behind the bootstrap decision so Excalidraw's initial mount `onChange` can't broadcast the cached scene.
- Whiteboards in collaboration mode now sync to `document.content` every 2s instead of 10s, matching the non-collab debounce. Narrows the stale-content window for non-collab readers and reduces the `yjs_state` / `content` desync window.

## [0.38.0] - 2026-04-10

### Added

- New `whiteboard` document type backed by Excalidraw
  - Create whiteboards via a new "Document type" dropdown on the Create Document dialog
  - Lazy-loaded canvas with full Excalidraw toolset (shapes, freehand, arrows, text, images)
  - Live collaboration via the existing Yjs WebSocket — whiteboard scene is mirrored to a single-key Y.Map and persisted alongside text documents
  - Theme syncs with the app's light/dark mode
  - Reuses the existing permissions, tags, comments, templates, and project-attachment infrastructure
  - Templates are filtered by document type so users don't accidentally copy a Lexical template into a whiteboard slot

### Fixed

- `normalize_document_content` is now type-aware so non-Lexical document content (whiteboard scenes, file metadata) isn't silently mutated to inject a Lexical `root` paragraph on save

## [0.37.0] - 2026-04-09

### Added

- Offline mode for the document editor
  - Persistent mode-aware toast when the device loses network connectivity
  - New "Offline" state in the collaboration status badge (now also shown in non-collaborative mode)
  - Autosave is skipped while offline and automatically retries on reconnect, so edits aren't lost
  - Uses `@capacitor/network` for accurate status on native, `navigator.onLine` on web

### Changed

- **React 18.3 → 19.2.** Bumped `react`, `react-dom`, `@types/react`, and `@types/react-dom` to 19.x. Required widening a drag-scroll hook's ref type to accept the new nullable `RefObject<T | null>`, importing `JSX` from `react` in a legacy Lexical `EmbedNode` (React 19 removed the global `JSX` namespace), and deleting two unused editor shim files that imported the now-removed `react-dom/test-utils`. All major peer deps (Lexical, Radix, TanStack Query/Router, cmdk, sonner, Testing Library 16) already declared `^19` support.
- **react-i18next 16 → 17** and **i18next 25 → 26.** Major bumps; react-i18next 17 requires i18next ≥ 26. None of i18next 26's breaking changes (`initImmediate`, legacy monolithic `format` function, `showSupportNotice`, `simplifyPluralSuffix`) are used in our config.
- Bumped `sqlmodel` 0.0.37 → 0.0.38 (backend ORM).
- Bumped `vite` 7.3.1 → 7.3.2, `msw` 2.12.14 → 2.13.0, `i18next-http-backend` 3.0.2 → 3.0.4, `@types/node` 25.5.0 → 25.5.2, `email-validator` 2.1.1 → 2.3.0, `python-multipart` 0.0.22 → 0.0.24.

### Fixed

- Document edits saved in non-collaborative mode are no longer overwritten by a stale `yjs_state` when re-enabling live collaboration. The document update endpoint now clears `yjs_state` and invalidates any empty in-memory collaboration room whenever content is written via the REST PATCH.

## [0.36.2] - 2026-04-08

### Added

- Table action menu in the document editor — click the chevron in any table cell to insert/delete rows and columns, toggle header rows/columns, or delete the table

### Fixed

- Fix tables shrinking from full width after deleting a column (changed table CSS from `w-fit` to `w-full`)
- Fix empty table rows/columns being removed during markdown round-trip (divider regex matched empty cells as header separators)

## [0.36.1] - 2026-04-06

### Added

- Global "Add Task" wizard dialog accessible from My Tasks, Tasks I Created, and the Command Center (Ctrl+K)
  - Multi-step flow: select guild → initiative → project → opens task composer on that project
  - Remembers last-used project for quick repeat task creation
  - Auto-skips steps when only one option exists (single guild or initiative)
  - Only shows projects the user has write access to

### Fixed

- Replace `imghdr` module with magic-bytes detection for Python 3.13 compatibility
- Fix double bottom inset on Android when the keyboard is visible (Capacitor SystemBars and safe-area plugin both applying insets)
- Remove `EdgeToEdge.enable()` to prevent conflict with safe-area plugin's inset management

## [0.36.0] - 2026-04-04

### Added

- Automations initiative tool (infra/paid feature, disabled by default)
  - Dual-layer feature gating: `ENABLE_AUTOMATIONS` env var (infrastructure) + per-initiative `automations_enabled` toggle
  - `automations_enabled` and `create_automations` permission keys with role-based access control
  - Stub `GET /automations` API endpoint for future pipeline integration
  - `GET /settings/automations-config` public endpoint for runtime feature discovery
  - Sidebar link with Zap icon, initiative settings toggle, and placeholder page
  - Build-time `VITE_ENABLE_AUTOMATIONS` flag for complete frontend tree-shaking in public builds
- Visual automation flow editor (n8n / Home Assistant style)
  - Drag-and-drop canvas powered by `@xyflow/react` with pan, zoom, and minimap
  - 5 node types: Trigger, Action, Condition (if/else branch), Delay, Loop (for-each)
  - Animated bezier edges with delete-on-hover
  - Node palette sidebar for dragging new nodes onto the canvas
  - Property inspector panel (Sheet) with type-specific forms
  - Automations list view with create/delete and card grid
  - 7 action types: send webhook, update task, send notification, add/remove tag, move to project, archive task
- Automation flow CRUD API with graph validation (DAG check, single trigger enforcement)
  - Full flow persistence to database (replaces localStorage)
  - Run history endpoints for execution logs
  - Frontend migrated to React Query hooks backed by backend API
- `POST /notifications/send` endpoint for engine-driven push notifications
- Redis service added to docker-compose (commented, for infra deployments)
- Automation engine backend infrastructure
  - Database tables: `automation_flows`, `automation_runs`, `automation_run_steps` with full RLS
  - `automation_engine` PostgreSQL role with BYPASSRLS for direct engine writes
  - Redis Streams event publisher for domain events (`task_created`, `task_updated`)
  - Service token authentication (`AUTOMATION_SERVICE_TOKEN`) for engine API callbacks
  - `REDIS_URL` config setting for event bus connectivity
- Dual Docker image CI/CD: publishes both `initiative` (public) and `initiative-infra` (paid) images
- Vite config now loads `.env` files from `backend/` directory for shared env vars
- Added Ctrl+S / Cmd+S keyboard shortcut to save in the document editor

### Fixed

- Cross-guild task/event links in My Calendar and My Tasks calendar view now navigate to the correct guild instead of the active guild

### Changed

- Bumped Lexical editor from 0.41 to 0.42 (all packages unified)
- Bumped asyncpg from 0.29.0 to 0.31.0
- Bumped httpx from 0.27.0 to 0.28.1
- Bumped SQLModel from 0.0.24 to 0.0.37
- Bumped pycrdt from 0.12.46 to 0.12.50
- Bumped PyJWT from 2.11.0 to 2.12.0
- Updated Orval to 8.6.2

### Removed

- Removed unused dependencies: `radix-ui` (unified), `@tanstack/router-devtools`, `autoprefixer`, `postcss`, `@tailwindcss/postcss`, `lodash`, `@types/lodash`
- Deleted unused `postcss.config.js`

## [0.35.0] - 2026-03-26

### Added

- Calendar events feature with Google Calendar-like UI
  - Initiative-scoped events with title, description, location, date/time, color, and recurrence
  - Attendee system with RSVP (pending, accepted, declined, tentative)
  - `events_enabled` toggle and `create_events` permission key on initiatives
  - Full CRUD, attendee management, RSVP, tags, and document attachment endpoints
- Reusable multi-view CalendarView component (day, week, month, year, list)
  - Month: multi-day spanning bars for all-day events, dot+time+title for timed events
  - Week/Day: positioned cards spanning full hour range with colored sidebar
  - Year: mini-month grids with per-event color dots or count badges
  - List: date, weekday, description, stacked attendee avatars with tooltip, time range
- Calendar sidebar link under each initiative with CalendarDays icon
- Event creation via clicking calendar day slots with date/time pre-fill
- Attendee picker using initiative members with searchable combobox
- Task recurrence selector reused for event recurrence

- Calendar view toggle on My Tasks and Created Tasks pages
- My Calendar page: cross-guild unified calendar combining tasks and events
  - Filters for status category, priority, and guild (persisted to local storage)
  - Events toggle to show/hide calendar events alongside tasks
  - Global calendar events backend endpoint (`GET /api/v1/calendar-events/global`)
- Filter and sort preferences persisted to local storage on My Tasks, Tasks I Created, My Projects, and My Documents pages
- Spanish and French translations for My Calendar page
- iCal (.ics) import/export for calendar events
  - Export events as `.ics` files (per-guild and cross-guild)
  - Import events from `.ics` files with preview and initiative selection
  - RRULE recurrence mapping (best-effort bidirectional conversion)
  - Export/import buttons on guild Events page and My Calendar page
  - Spanish and French translations for import/export UI

### Changed

- Replaced ProjectCalendarView with generic CalendarView component for project tasks
- Project task calendar now shows assignee avatars in list view
- Initiative settings: Calendar toggle alongside Queues under Advanced Tools

### Fixed

- Calendar event update endpoint now validates date ordering and 24-hour limit for timed events
- Document attachment on calendar events now scoped to guild, preventing cross-guild association

## [0.34.2] - 2026-03-18

### Fixed

- PWA manifest: fixed icon paths, split `any maskable` purpose into separate entries, added desktop and mobile screenshots for richer install UI

## [0.34.1] - 2026-03-03

### Changed

- Moved search/Cmd+K button from sidebar footer to top bar for better discoverability
- Aligned sidebar header, top bar, and activity sidebar header heights

### Fixed

- Lighthouse accessibility: added aria-labels to home link, progress bars, task status select, page size select, and searchable combobox
- Lighthouse SEO: added meta description and robots.txt
- Lighthouse performance: deferred Google Fonts loading, added Cache-Control headers for hashed static assets

## [0.34.0] - 2026-03-01

### Added

- French (Français) locale — full translation of all 19 frontend namespaces and backend email templates
- Image and Markdown file uploads for documents — images display with lightbox zoom, markdown files render with source/rendered toggle
- Heading anchor links (`#slug`) in both markdown file viewer and native Lexical editor — clicking scrolls to the matching heading

### Fixed

- `app_admin` role missing grants on `uploads` table — caused `permission denied` errors when serving uploaded files
- Markdown file upload rejected with 400 error when `python-magic` returns variant MIME type (e.g. `text/x-markdown`)

## [0.33.2] - 2026-02-28

### Added

- Column header sorting on the My Projects page (name and updated columns) with server-side sort support

## [0.33.1] - 2026-02-27

### Security

- Docker container now runs as non-root user (`app`, UID/GID 1000 by default) instead of root — compatible with rootless Docker and Podman. Set `PUID`/`PGID` environment variables to customize (e.g. `PUID=99 PGID=100` for Unraid's `nobody:users`)

### Fixed

- `app_admin` role missing grants on queue tables — caused `permission denied for table queues` errors for background jobs and seed scripts
- Added `ALTER DEFAULT PRIVILEGES` for `app_admin` so future migrations automatically inherit grants (previously only `app_user` had default privileges)

### Upgrade Notes

- **Uploads volume ownership**: The container now runs as a non-root user (UID 1000 by default). If file uploads fail after upgrading, fix ownership on the host: `chown -R 1000:1000 ./uploads`. Alternatively, set `PUID` and `PGID` to match your host user (e.g. `PUID=99 PGID=100` for Unraid)

## [0.33.0] - 2026-02-27

### Added

- Queue feature: turn/priority tracking with turn controls (start, stop, advance, previous, reset), per-item user/document/task linking, and tag support
- Queue DAC (Discretionary Access Control): user-level and role-based permissions with read/write/owner levels
- Queue settings page with details editing, role/user permission management, and delete
- Queue user permissions table: filtering by name, multiselect with bulk access change/remove, pagination, and "Add All" button
- Queue backend integration tests (19 tests covering CRUD, items, turns, DAC, and associations)
- Queue frontend and backend test factories
- Initiative-level feature flags: per-initiative toggle to enable/disable advanced tools like Queues; Advanced Tools accordion in create and settings dialogs
- Queues tab on initiative detail page when queues are enabled
- Queue list filter bar with search, active/inactive status filter, and initiative filter

### Changed

- Roles tab redesigned from data table to card-per-role layout with grouped permission switches and an Advanced Tools accordion, scaling to any number of permissions without horizontal scrolling
- Removed standalone "All Queues" sidebar link; queues are now accessed per-initiative

## [0.32.4] - 2026-02-26

### Security

- HTML and HTM files served via `/uploads/*` now force `Content-Disposition: attachment` and `Content-Security-Policy: script-src 'none'`, preventing stored XSS via uploaded HTML documents (GHSA-v38c-x27x-p584, reported by G3XAR).
- JWT tokens are now invalidated on logout and password change via server-side token versioning, preventing continued access with a captured token (GHSA-hww6-3fww-xw3h, reported by G3XAR). All active sessions will be signed out on first deployment of this update.

## [0.32.3] - 2026-02-26

### Added

- Dark Knight color theme: AMOLED true-black dark mode with dark maroon and bat-signal yellow accents
- ORC color theme: earthy green theme with vivid orc-skin green accents and cave/swamp dark mode
- Aboleth color theme: Monokai-inspired dark lair with vivid bioluminescent accent colors (lime, cyan, purple, orange, hot pink)
- Unicorn color theme: Bold and bright rainbow colors

## [0.32.2] - 2026-02-25

### Security

- Sensitive database fields are now encrypted at rest using Fernet (AES-128-CBC): AI API keys at platform, guild, and user levels; OIDC client secret; SMTP password. Existing data is migrated automatically via Alembic. The encryption key is derived from `SECRET_KEY`.
- User email addresses are now encrypted at rest. The `users` table stores an HMAC-SHA256 hash (`email_hash`) for fast indexed lookups and a Fernet ciphertext (`email_encrypted`) for display/sending; the plaintext `email` column is removed. Guild invite email addresses are also encrypted. Existing data is migrated automatically.
- Uploaded files now require authentication to access; the `/uploads/*` path no longer serves files to unauthenticated users. The backend validates the user's token from the `Authorization` header (reported by Adem Kucuk).
- Uploaded files are now restricted to members of the guild they were uploaded in. The backend tracks file→guild ownership in a new `uploads` table and returns 403 to authenticated users who are not members of the owning guild. Covers image attachments, document file uploads (PDF, DOCX, etc.), and files created by duplicate/copy/template operations. Pre-existing files without a database record remain accessible to any authenticated user for backwards compatibility.
- File-type documents (PDFs, DOCX, etc.) now enforce document-level read permission on download. A new `GET /api/v1/documents/{id}/download` endpoint replaces direct `/uploads/*` access for file documents; guild membership alone is no longer sufficient — the requester must have explicit read, write, or owner permission on the document. Inline viewing (`?inline=1`) and attachment download use the same permission check.
- Web sessions now use HttpOnly `SameSite=Lax` cookies instead of `localStorage` for JWT storage, eliminating XSS token theft risk and removing the JWT from browser history/server logs. The cookie is sent automatically for all requests including media (`<img>`, `<iframe>`); native (Capacitor) is unchanged and continues to use DeviceToken headers stored in Capacitor Preferences.
- Replaced `python-jose` with `PyJWT` for JWT handling. `python-jose` (through 3.3.0) has an algorithm confusion vulnerability with OpenSSH ECDSA keys and other key formats (similar to CVE-2022-29217) and is no longer maintained.
- Rate limiting added to `/uploads/*` (600 req/min) and `GET /documents/{id}/download` (30 req/min); file download access is now logged.
- Upgraded `python-multipart` from 0.0.9 to 0.0.22, fixing a DoS via malformed `multipart/form-data` boundary and an arbitrary file write via non-default configuration.
- Added Dependabot configuration (`.github/dependabot.yml`) for automated dependency update PRs on backend, frontend, and GitHub Actions.

### Changed

- Command Center search placeholder now reads "Search in \<guild name\>" instead of a generic string

## [0.32.1] - 2026-02-23

### Fixed

- My Tasks date groups (Overdue, Today, This Week, etc.) now respect the user's timezone — backend uses `AT TIME ZONE` with a `tz` query parameter instead of UTC `now()`
- `useAllDocumentIds` cache corruption after visiting the Initiatives page — fixed React Query key collision with `useDocumentsList`

### Changed

- Command Center shows project emoji icons and file-type-specific document icons (PDF, Word, Excel, PowerPoint) with color coding
- Extract shared `getDocumentIcon` / `getDocumentIconColor` helpers in `fileUtils.ts` — used by both Command Center and DocumentCard

## [0.32.0] - 2026-02-23

### Added

- Command Center (`⌘K` / `Ctrl+K`) for quick navigation to projects, tasks, documents, and pages with fuzzy search — accessible via sidebar shortcut badge or 3-finger tap on mobile
- Reusable `StatusMessage` component for consistent error states across detail pages
- Distinct 404/403 error messages on Project, Document, Tag, and Initiative detail pages using `Empty` card layout with contextual icons
- "Guild not available" page when navigating to a guild the user isn't a member of (replaces silent redirect)
- Rate-limit error message ("Too many requests") instead of misleading "Check your credentials" on login/register
- Row virtualization for DataTable using `@tanstack/react-virtual` — only visible rows exist in the DOM, tested with 10k tasks
- Virtualized Gantt view with sticky day headers and pinned task name column
- Virtualized Kanban columns (activates above 20 tasks per column) with memoized card components and DnD compatibility
- Collapse all / expand all buttons for sidebar initiative list and tag browser
- Memoized virtual cell rendering to prevent expensive re-renders during scroll

### Fixed

- Navigating to an inaccessible guild no longer poisons the active guild state, which previously caused "Unable to load" errors on the home page after redirect
- Dashboard "Recent Comments" no longer leaks comments from projects/documents the user lacks access to — filters by DAC permissions (direct + role-based)

### Security

- Add initiative-scoped RESTRICTIVE RLS policies to `tasks`, `task_statuses`, `subtasks`, and `task_assignees` — previously only had guild-level isolation

### Changed

- Vendored editor color picker (~1,800 lines) — replaced with existing shadcn-io color picker + Popover in font color and background color toolbar plugins
- Lazy-load editor color picker content so the `color` npm package is only fetched when a user opens the font/background color popover
- Lazy-load 4 profile settings pages (profile, notifications, interface, danger zone) — reduces index bundle by ~75 kB
- Replace pointless `React.lazy()` with static imports for `LexicalTypeaheadMenuPlugin` and `emoji-list` — both were already pinned to the editor chunk by co-located static imports, eliminating Vite "dynamically and statically imported" warnings
- Sidebar collapsed sections (initiatives, tags) no longer mount child DOM nodes — lazy-render on expand
- Skip `useSortable` hooks when drag-and-drop is disabled (sorting/grouping active) for better scroll performance
- Keep previous React Query data as placeholder for snappier page navigation
- - Replaced `sort_by`/`sort_dir` string parameters on the tasks list endpoint with a structured `sorting` JSON parameter (`SortField[]`) — enables multi-column sorting (e.g. date group then due date) using the same pattern as `conditions` uses `FilterCondition[]`
- Frontend task tables (`useGlobalTasksTable`, `TagTasksTable`, dashboard, route loaders) now pass `SortField[]` arrays instead of individual sort strings

## [0.31.5] - 2026-02-20

### Fixed

- `OIDC_ENABLED` env var no longer prevents admins from disabling OIDC via the UI — env var now only seeds on first boot instead of overriding the DB value on every read
- Guild switching no longer shows stale sidebar data — restored query cache invalidation on guild switch that was accidentally removed during React Query migration
- HTML `<strong>` tags rendered as literal text in delete confirmation dialogs — switched to react-i18next `Trans` component for proper bold rendering in initiative, guild, and settings dialogs (en + es locales)
- Defensive `Array.isArray` guard in document template queries to prevent crash on non-array data
- Admin initiative member role promotion (500 error) — endpoint referenced non-existent `.role` attribute on `InitiativeMember`; fixed to resolve roles via `role_id` FK
- Admin delete user dialog 404s when fetching initiative members across guilds — added admin endpoint `GET /admin/initiatives/{id}/members` that bypasses RLS
- Self-deletion dialog 404s when fetching initiative members across guilds — added user endpoint `GET /users/me/initiative-members/{id}` that bypasses RLS for owned initiatives

### Changed

- Centralized settings and AI settings mutation hooks (Phase 4a) — 13 new hooks in `useSettings.ts` and `useAISettings.ts` replace inline mutations across 7 settings pages/components; added `MutationOpts` to `useUpdateRoleLabels`
- Centralized remaining mutation hooks (Phase 4b) — 22 new hooks across `useAdmin.ts`, `useUsers.ts`, `useSecurity.ts`, and new `useImports.ts`; added `MutationOpts` to 11 existing hooks in `useComments.ts`, `useTags.ts`, `useNotifications.ts`; no `.tsx` file imports `useMutation` directly
- Centralized inline `useMutation` hooks for tasks, subtasks, task statuses, project members, role permissions, and project documents into domain hook files (`useTasks.ts`, `useProjects.ts`) — replaces ~50 inline mutations across 15 component/page files
- Consolidated standalone `useProjectFavoriteMutation` and `useProjectPinMutation` hooks into `useProjects.ts` as `useToggleProjectFavorite` and `useToggleProjectPin`
- All mutation hooks now accept an optional `MutationOpts` parameter, allowing callers to provide `onSuccess`, `onError`, `onSettled`, and other mutation options
- Added shared `MutationOpts` type (`frontend/src/types/mutation.ts`)
- Fixed `apiMutator` to merge request options (custom headers were silently ignored)
- Optimized database indexes: dropped 9 redundant indexes (PK-subsumed and unique-constraint-duplicated) and added 6 high-priority FK/reverse-lookup indexes for `task_assignees`, `initiative_members`, `project_permissions`, `document_permissions`, `initiatives`, and `projects`
- Synced model declarations (`index=True`) with actual database indexes for maintainability
- Test database setup is now fully automatic — `conftest.py` creates the `initiative_test` database and runs migrations on first test run, removing the need for manual `setup_test_db.sh`
- Centralized document mutations into `useDocuments.ts` — new hooks for create, upload, duplicate, copy, member CRUD (individual + bulk), role permission CRUD, and AI summary generation; replaces inline mutations across DocumentSettingsPage, DocumentDetailPage, DocumentsPage, CreateDocumentDialog, CreateWikilinkDocumentDialog, and DocumentSummary
- Centralized initiative mutations into `useInitiatives.ts` with `MutationOpts` support — replaces inline mutations in InitiativeSettingsPage

## [0.31.4] - 2026-02-20

### Fixed

- Mobile (Capacitor) app crash on startup — Orval-generated API requests used a hardcoded empty `baseURL`, causing them to hit the WebView origin instead of the backend server and receiving HTML instead of JSON
- Race condition where child provider effects fired API calls before `ServerProvider` set the backend URL from storage
- Locale file 404s on mobile — `navigator.language` returns full locale codes (e.g., `en-US`) but only `en/` directories exist; added `load: "languageOnly"` to i18next config
- `useProjectFavoriteMutation` and `useProjectPinMutation` crashing when toggling — `setQueryData` updaters treated paginated `ProjectListResponse` as a plain array
- Defensive `Array.isArray` guard in `initStorage()` and AppSidebar favorites to prevent crashes from unexpected Capacitor bridge responses

## [0.31.3] - 2026-02-20

### Added

- Paginated `GET /api/v1/projects/` endpoint with `page` and `page_size` query params (`page_size=0` returns all, preserving backward compatibility)
- `MentionEntityType` enum for mention search endpoint — replaces open-ended string parameter
- `PermissionKey` enum enforced at API, model, and database levels — adds CHECK constraint to `initiative_role_permissions.permission_key` column
- Alembic migration to add CHECK constraint for valid `permission_key` values

### Changed

- Centralized remaining inline queries — `GuildDashboardPage`, `MyProjectsPage`, `MyDocumentsPage` now use domain hooks (`useProjects`, `useInitiatives`, `useTasks`, `useRecentComments`, `useGlobalProjects`, `useGlobalDocuments`)
- Eliminated direct `useQueryClient` usage from pages/components — added `usePrefetchTasks`, `usePrefetchGlobalProjects`, `usePrefetchGlobalDocuments`, `usePrefetchDocumentsList`, `useSetDocumentCache`, `useCommentsCache`, and `useUpdateRoleLabels` hooks
- Added ESLint rule (`no-restricted-imports`) to prevent direct `useQuery`/`useQueryClient` imports outside `src/api/` and `src/hooks/`
- Migrated `useGlobalProjects` from raw `apiClient` to Orval-generated `listGlobalProjectsApiV1ProjectsGlobalGet` with generated query keys
- Removed custom `ProjectListResponse`, `MentionEntityType`, and `PermissionKey` types from `frontend/src/types/api.ts` — now generated from backend OpenAPI spec
- Moved `TaskWeekPosition` to `lib/recurrence.ts` and `CommentWithReplies` to `CommentSection.tsx` — `types/api.ts` is now a pure re-export of generated schemas

### Fixed

- Template document dropdown in CreateDocumentDialog not showing templates accessible via role-based permissions (only showed templates with explicit user permissions)
- Document/attachment uploads returning 422 error due to hardcoded `Content-Type: application/json` header overriding FormData auto-detection
- Subtask checklist items failed to load ("Unable to load checklist items right now") due to double-unwrapping of API responses in `useSubtasks` hook and `TaskChecklist` mutations

## [0.31.2] - 2026-02-19

### Added

- Centralized query key invalidation helpers (`frontend/src/api/query-keys.ts`) with domain-specific functions for consistent cache management

### Changed

- Migrated ~70 frontend files from manual `apiClient` calls to Orval-generated functions and React Query hooks
  - Pages: all project, task, document, initiative, settings, and user settings pages
  - Components: sidebar, comment section, import dialogs, bulk edit dialogs, task checklist, notifications
  - Hooks: tags, roles, AI settings, interface colors, version check, push notifications, realtime updates
  - Route loaders: all `ensureQueryData` calls updated to use generated fetchers and query keys
- Centralized frontend API query hooks into domain-specific hook files (`useDocuments`, `useProjects`, `useInitiatives`, `useComments`, `useNotifications`) following the `useTags` pattern — replaces inline `useQuery`/`useMutation` calls across pages with clean, reusable hooks that include error toasts and cache invalidation
- Created `usePagination` hook for reusable page/pageSize state management with URL search param sync
- Replaced manual query keys (e.g., `["projects"]`) with generated URL-based keys (e.g., `["/api/v1/projects/"]`)
- Replaced manual `queryClient.invalidateQueries()` calls with domain-specific helpers from `query-keys.ts`
- Orval config updated to `httpClient: "axios"` for clean return types (no discriminated union wrappers)
- API mutator updated to accept `AxiosRequestConfig` and prevent double URL prefixing with `baseURL: ""`
- Removed duplicate `TaskListResponse` and `DocumentListResponse` type definitions from `types/api.ts` in favor of Orval-generated versions
- Deleted `src/api/notifications.ts` — all consumers migrated to `useNotifications` hooks
- Centralized remaining inline queries — `GuildDashboardPage`, `MyProjectsPage`, `MyDocumentsPage` now use domain hooks (`useProjects`, `useInitiatives`, `useTasks`, `useRecentComments`, `useGlobalProjects`, `useGlobalDocuments`)
- Eliminated direct `useQueryClient` usage from pages/components — added `usePrefetchTasks`, `usePrefetchGlobalProjects`, `usePrefetchGlobalDocuments`, `usePrefetchDocumentsList`, `useSetDocumentCache`, `useCommentsCache`, and `useUpdateRoleLabels` hooks
- Added ESLint rule (`no-restricted-imports`) to prevent direct `useQuery`/`useQueryClient` imports outside `src/api/` and `src/hooks/`
- Migrated direct type imports from `@/types/api` to `@/api/generated/initiativeAPI.schemas` — types that exist directly in the generated Orval schemas are now imported from source, reducing reliance on the backward-compat alias layer

### Fixed

- Tasks endpoint returned no results when requesting tasks for a template project

## [0.31.1] - 2026-02-18

### Fixed

- Translation files were cached by the browser across deploys, causing newly added i18n keys to render as raw strings — translation fetches now include a version query param for cache busting

## [0.31.0] - 2026-02-18

### Added

- **Home sidebar mode** — clicking the logo now shows a user-centric sidebar (Discord-style) with personal navigation links instead of guild content
  - My Tasks (existing, refactored)
  - Tasks I Created — cross-guild list of tasks you created, with inline assignee display
  - My Projects — cross-guild list of projects you have access to
  - My Documents — cross-guild list of documents you own
  - My Stats (existing)
- `created_by_id` column on Task model to track who created each task
- `GET /tasks/?scope=global_created` endpoint — lists tasks created by the current user across all guilds
- `GET /projects/global` endpoint — lists projects the user can access across all guilds with pagination, guild filter, and search
- `GET /documents/?scope=global` endpoint — lists documents owned by the current user across all guilds
- Sequential Alembic migration naming convention (`YYYYMMDD_NNNN`) for chronological sorting
- Access controls in Create Project and Create Document dialogs via a collapsible "Advanced options" accordion
  - Role-based permission grants: assign access by initiative role at creation time
  - User-based permission grants: assign access to specific members at creation time
  - "Add all initiative members" opt-out toggle for projects (replaces invisible auto-add behavior)
- Shared `CreateAccessControl` component for role/user permission pickers

### Changed

- Sidebar now switches between Home mode (non-guild routes) and Guild mode (guild routes) based on the current URL
- MyTasksPage refactored to use shared `useGlobalTasksTable` hook, `GlobalTaskFilters`, and `globalTaskColumns` — shared across My Tasks and Tasks I Created pages
- Creating a project no longer auto-adds all initiative members as read — permissions are now explicitly controlled via the create dialog
- Project creation notifications are now scoped to only users who were granted access

### Fixed

- Post-baseline Alembic migration detection no longer crashes on startup — `init_db` now checks for `app_user` role existence instead of exact revision match
- Guild admins and initiative managers now follow DAC (Discretionary Access Control) for documents and projects — these roles no longer grant implicit owner-level access to every resource
- Guild admins can now add themselves to initiatives and manage initiative membership (previously required being an initiative manager)
- Collaboration WebSocket endpoint now uses pure DAC — matches REST endpoint behavior instead of bypassing access checks for admins/managers
- Fixed `handle_owner_removal` crash (`AttributeError: role`) when removing a member from an initiative
- Documents tag tree view: selecting "Not tagged" now filters server-side with correct pagination instead of client-side filtering per page
- Documents tag tree view: selecting a tag with no matching documents no longer replaces the sidebar with the empty state card
- AppSidebar crash when initiative query data is not an array

## [0.30.1] - 2026-02-16

### Added

- Auto-generated frontend TypeScript types and React Query hooks from the backend OpenAPI spec using Orval
  - Generated files in `frontend/src/api/generated/` committed to the repo so the frontend builds without a running backend
  - `frontend/src/types/api.ts` now re-exports generated types with backward-compatible aliases (e.g., `Task = TaskListRead`)
  - Custom Axios mutator (`frontend/src/api/mutator.ts`) preserves existing auth/guild interceptors
  - `pnpm generate:api` script to regenerate from a running backend
- CI check (`check-generated-types` job) that fails when generated frontend types drift from backend schemas
- `backend/scripts/export_openapi.py` to export OpenAPI spec without a running server (used by CI)

### Changed

- Backend Pydantic schemas now use `ConfigDict(json_schema_serialization_defaults_required=True)` so optional fields with defaults appear as required in the OpenAPI spec, producing cleaner generated types
- `frontend/src/types/api.ts` replaced ~800 lines of hand-maintained type definitions with re-exports from Orval-generated types
- Excluded `src/api/generated/**` from ESLint (Orval generates function overloads that trigger `no-redeclare`)
- CI backend test scoping now treats `app/schemas/` as shared infrastructure, triggering a full test run when schemas change
- Guild Dashboard landing page at `/g/:guildId/` with project health, velocity chart, upcoming tasks, recent projects, and initiative overview
- Guild switching now navigates to the dashboard instead of preserving the previous sub-path
- "All Projects" and "All Documents" links in the sidebar between favorites and initiatives
- Composite database indexes for query performance: tasks (project + archived, due date + status, updated_at), guild memberships (user + guild), and documents (updated_at)
- Squashed all 76 Alembic migrations into a single idempotent baseline migration — fresh installs no longer require `docker/init-db.sh` to pre-create database roles
- `DATABASE_URL_APP` and `DATABASE_URL_ADMIN` are now **required** environment variables (previously fell back to `DATABASE_URL`, which silently ran the app as superuser without RLS enforcement)
- RLS is now always enforced — removed the `ENABLE_RLS` configuration flag
- Migrations always run using `DATABASE_URL` (superuser), fixing the env.py URL override bug that caused migrations to use the wrong connection
- Reorganized backend security architecture into two centralized service modules:
  - `rls.py` — Mandatory Access Control: guild isolation, guild RBAC (admin-only writes), initiative membership, and initiative RBAC via PermissionKey
  - `permissions.py` — Discretionary Access Control: project/document-level read/write/owner permissions with visibility subqueries
- Centralized guild admin enforcement across all endpoints via `rls_service.is_guild_admin()` and `rls_service.require_guild_admin()`
- Moved initiative security checks (`is_initiative_manager`, `check_initiative_permission`, `has_feature_access`) from initiatives service to `rls.py` (backward-compatible re-exports preserved)
- Replaced duplicated permission logic in endpoint files (projects, documents, tasks, tags, imports, collaboration) with shared helpers from `permissions.py`
- Consolidated visibility subquery patterns (`visible_project_ids_subquery`, `visible_document_ids_subquery`) to eliminate duplication across listing endpoints

### Removed

- `ENABLE_RLS` environment variable — RLS is always active; remove this from your `.env` if present
- `init_models()` backwards-compatibility alias (use `import app.db.base` directly)
- `docker/init-db.sh` — database role creation is now handled by the baseline migration itself
- 76 individual migration files replaced by single baseline (existing v0.30.0 databases upgrade seamlessly)

### Upgrade Notes

- **From v0.30.0**: No action needed — the baseline migration is a no-op for existing databases. You can safely remove `docker/init-db.sh` if present.
- **From pre-v0.30.0 (v0.14.1–v0.29.x)**: The application will detect the old schema and exit with instructions. Run the upgrade script before starting:
  ```bash
  curl -fsSL https://raw.githubusercontent.com/Morelitea/initiative/main/scripts/upgrade-to-baseline.sql \
    -o upgrade-to-baseline.sql
  psql -v ON_ERROR_STOP=1 -f upgrade-to-baseline.sql "$DATABASE_URL"
  ```
  If psql is not available on your host (e.g. Synology, Unraid), pipe through the Postgres container:
  ```bash
  curl -fsSL https://raw.githubusercontent.com/Morelitea/initiative/main/scripts/upgrade-to-baseline.sql | \
    docker exec -i initiative-db psql -v ON_ERROR_STOP=1 -U initiative -d initiative
  ```
  Then restart the application. The baseline migration will create database roles, RLS policies, and grants automatically.

## [0.30.0] - 2026-02-15

### Added

- Full internationalization (i18n) infrastructure with react-i18next and namespace-based translation loading
  - 16 translation namespaces covering all app areas: auth, nav, projects, tasks, documents, settings, guilds, initiatives, tags, stats, import, notifications, landing, errors, dates, common
  - Language selector in user interface settings (infrastructure ready for additional languages)
  - User `locale` preference stored in database with Alembic migration
  - Backend email i18n with JSON-based template loader and `{{variable}}` interpolation
  - Backend error code constants (`messages.py`) mapped to frontend-localized messages via `errors.json`
- All user-facing strings externalized across the entire application:
  - Auth flow (login, register, password reset, email verification)
  - Navigation, sidebar, and guild switcher
  - Project CRUD, settings, permissions, and kanban/table/timeline views
  - Task editing, assignments, recurrence, priorities, and status management
  - Document editor toolbar, comments, mentions, and emoji picker
  - Initiative and guild management, member tables, and invite flows
  - User settings (profile, security, notifications, interface, import/export)
  - Platform admin pages (users, settings, OIDC configuration)
  - Statistics and reporting pages
  - Landing page with all marketing copy
  - Email templates (verification, password reset, task assignment, mentions, overdue notifications)
- Spanish (es) locale — complete translations for all 16 frontend namespaces and backend email templates (these are AI generated translations, contributions wanted)
- Locale-aware AI content generation (subtasks, descriptions, document summaries respond in user's language)
- `useDateLocale` hook for date-fns locale resolution across the app
- Locale key parity test (vitest) to catch missing/extra translation keys in CI

## [0.29.1] - 2026-02-13

### Fixed

- Hotfix docker entry script

## [0.29.0] - 2026-02-13

### Added

- OIDC claim-to-role mapping: automatically assign users to guilds and initiatives based on OIDC token claims (e.g., `groups`, `realm_access.roles`) on every login
  - Configurable claim path and mapping rules in Platform Settings > Auth
  - Supports guild and initiative target types with role selection
  - OIDC-managed memberships tracked separately from manual assignments; manual memberships are never overwritten
  - Stale OIDC-managed memberships automatically removed when claims change
- OIDC refresh token periodic re-sync: stores encrypted refresh tokens and periodically re-fetches userinfo claims in the background, keeping guild/initiative memberships in sync without requiring re-login
  - 5-minute poll cycle with 15-minute per-user sync interval
  - Automatic token rotation support; graceful handling of revoked tokens
  - `offline_access` added to default OIDC scopes for refresh token issuance
- Extracted background task runner into dedicated `background_tasks.py` module
- PKCE (S256) support for OIDC authentication, required by many identity providers
- Multi-sort support for task list API (`sort_by=date_group,due_date&sort_dir=asc,asc`)
- New cinematic landing page with parallax starfield, scroll-driven animations, interactive screenshot lightbox, and dark/light theme support
- No-guild empty state for users with no guild membership after login, with options to create a guild, redeem an invite, or log out
- "Source" column in guild and initiative member tables showing whether membership is managed by OIDC or manual

### Changed

- Renamed `OIDC_DISCOVERY_URL` env variable to `OIDC_ISSUER` (old name still works as fallback); issuer URL no longer requires `/.well-known/openid-configuration` suffix
- Guild deletion now uses a name-confirmation dialog instead of browser prompt
- Logout now clears the React Query cache to prevent stale data when switching accounts

### Fixed

- Role-based write users now appear in task assignee dropdowns (previously only explicit user permissions were considered)
- My Tasks page now sorts by date group (overdue, today, this week, this month, later) then by due date, matching the visual grouping order
- `BEHIND_PROXY=true` now passes `--proxy-headers` and `--forwarded-allow-ips` to Uvicorn so real client IPs appear in logs and `request.client.host` (#92)
- Users with no guild membership no longer get 500 errors; backend returns 403 with descriptive message
- Documents on project dashboard are now filtered by user's document-level permissions (guild admins see all)
- Project settings button in sidebar now correctly appears for users with role-based write access
- Removing a user from a guild or initiative now clears their task assignments
- OIDC sync membership removal now cleans up task assignments
- Fixed loading state flicker on no-guild screen caused by `useGuilds` dependency cycle

## [0.28.0] - 2026-02-11

### Added

- Server-side pagination for tasks: `GET /tasks/` now accepts `page`, `page_size`, `sort_by`, and `sort_dir` query params, returning paginated results with total count (`page_size=0` returns all for drag-and-drop views)
  - Server-side sorting for tasks with support for title, due date, start date, priority, created/updated timestamps, and manual sort order
  - Pagination and server-side sorting controls on My Tasks page and tag tasks table, with page synced to URL and hover prefetching
- Server-side pagination and sorting for documents: `GET /documents/` now accepts `page`, `page_size`, `sort_by`, and `sort_dir` query params, returning paginated and sorted results with total count
  - `GET /documents/counts` lightweight endpoint returning per-tag document counts for the tag tree sidebar
  - Pagination controls (prev/next, page size selector, page in URL) for all three document views (list, grid, tags)
  - Data prefetching on hover over pagination buttons for instant page transitions
- Role-based access control for projects and documents: grant read or write access to an entire initiative role as well as adding users individually
  - Role Access section in project and document settings pages for managing role-based permissions
  - Bulk role access management: grant or revoke role-based permissions across multiple selected documents at once
  - `my_permission_level` field in project and document API responses indicating the current user's effective access level
- Persistent storage abstraction (`storage.ts`) backed by Capacitor Preferences on mobile and localStorage on web, preventing data loss when mobile OS clears localStorage under memory pressure

### Changed

- Project settings page reorganized into tabbed layout (Details, Access, Task statuses, Advanced)
- Document settings page reorganized into tabbed layout (Details, Access, Advanced)
- Bulk edit access dialog restructured into Roles and Users tabs, each with grant/revoke action selector
- All frontend localStorage usage migrated to the new storage abstraction (~15 files)

## [0.27.0] - 2026-02-10

### Added

- Initiative-scoped Row-Level Security: users must be an initiative member to see its data (initiatives, projects, documents, roles). Guild admins and superadmins bypass this layer.

### Fixed

- My Stats page returning all zeros after RLS enforcement (endpoint now uses UserSessionDep for proper RLS context)
- User profile and self-update endpoints returning empty initiative roles under RLS enforcement
- Missing `guild_id` on initiative member records when creating initiatives or adding members, causing members to be invisible under RLS
- Stale initiative data returned after create/update due to SQLAlchemy identity map caching
- 64 pre-existing test failures caused by test infrastructure not keeping up with RLS, DAC, and role system changes

## [0.26.0] - 2026-02-08

### Added

- Per-channel notification preferences: independent Email and Mobile App (push) toggles for each notification category
- Email notifications for mentions, comments, and replies (previously only had push and in-app)
- Mobile App column on notification preferences page (shown when FCM is enabled)

### Changed

- In-app bell notifications now always fire regardless of user preferences
- Notification preferences page redesigned as a table with Email and Mobile App columns

### Fixed

- Mentions preference (`notify_mentions`) was missing from user update schemas, preventing it from being changed via API

## [0.25.5] - 2026-02-07

### Added

- Email column in project and document access tables for easier member identification

### Fixed

- Task status editing no longer crashes with 500 error for custom roles
- Task status management now uses project-level write access (DAC) instead of requiring initiative manager role
- Guild admins can now see all guild members in the Users settings table (was only visible to platform admins)

## [0.25.4] - 2026-02-07

### Fixed

- Attempt: My Tasks page now shows tasks from all guilds the user belongs to, not just the active guild (RLS SELECT policies now check membership instead of active guild)

## [0.25.3] - 2026-02-07

### Fixed

- Mobile deep links now correctly forward device token auth

## [0.25.2] - 2026-02-07

### Fixed

- OIDC login on mobile now issues a long-lived device token instead of a short-lived JWT, so sessions persist across app restarts

## [0.25.1] - 2026-02-07

### Fixed

- Tag badges now link to their tag detail page across all views (My Tasks, project table, Kanban, project previews, documents)
- Added tags column to My Tasks table
- Create project dialog no longer reopens after clicking cancel or create
- Make heading and filter styling more consistent across pages

## [0.25.0] - 2026-02-06

### Added

- **Row Level Security (RLS) enforcement** across all API endpoints
  - Database-level access control ensures users can only access data within their guild
  - All guild-scoped endpoints now set RLS context (user, guild, role) before querying
  - Super admin bypass via `app.is_superadmin` session variable
  - RLS policies added for tags, document_links, task_tags, project_tags, and document_tags tables
  - Guild table now has command-specific policies (SELECT/INSERT/UPDATE/DELETE) instead of a single blanket policy
  - Guild memberships allow cross-guild SELECT for own memberships (needed for guild list, leave checks)
  - NULLIF-safe policies prevent empty string cast crashes (fail-closed with 0 rows instead of 500 errors)

### Changed

- Admin endpoints now use dedicated admin database sessions (bypass RLS for cross-guild platform operations)
- Registration, invite acceptance, and account deletion use admin sessions (bootstrapping operations that span guilds)
- Database sessions pin their connection for the entire request lifetime to prevent RLS context loss after commits

### Upgrade Notes

**Docker deployments** should update their setup to enable RLS enforcement:

1. **Add the init script** — copy `docker/init-db.sh` from the repository into a `docker/` directory next to your `docker-compose.yml`. This script creates two PostgreSQL roles:
   - `app_user` — RLS-enforced, used for normal API queries
   - `app_admin` — BYPASSRLS, used for migrations and background jobs

2. **Update `docker-compose.yml`** — add the following to your `db` service:

   ```yaml
   services:
     db:
       environment:
         APP_USER_PASSWORD: ${APP_USER_PASSWORD:-app_user_password}
         APP_ADMIN_PASSWORD: ${APP_ADMIN_PASSWORD:-app_admin_password}
       volumes:
         - ./docker/init-db.sh:/docker-entrypoint-initdb.d/01-create-roles.sh
   ```

   And add these environment variables to your `initiative` service:

   ```yaml
   services:
     initiative:
       environment:
         # RLS-enforced connection (app_user role, no BYPASSRLS)
         DATABASE_URL_APP: postgresql+asyncpg://app_user:${APP_USER_PASSWORD:-app_user_password}@db:5432/initiative
         # Admin connection for migrations and background jobs (app_admin role, BYPASSRLS)
         DATABASE_URL_ADMIN: postgresql+asyncpg://app_admin:${APP_ADMIN_PASSWORD:-app_admin_password}@db:5432/initiative
   ```

   See `docker-compose.example.yml` for a complete reference.

3. **Fresh databases only** — the init script runs on first `docker-compose up` (when the postgres data volume is empty). For existing databases, the Alembic migration (`20260207_0040`) creates the roles automatically. You will still need to set `DATABASE_URL_APP` and `DATABASE_URL_ADMIN` environment variables.

4. **Backward compatible** — if `DATABASE_URL_APP` is not set, the app falls back to `DATABASE_URL` and RLS remains inert (existing behavior).

## [0.24.0] - 2026-02-06

### Added

- Bulk edit tags for tasks and documents (add/remove modes)
- Bulk edit access permissions for documents (grant/revoke modes)
- Tag detail page now uses a tabbed layout (Tasks, Projects, Documents) with full filtering, sorting, and inline status/priority editing

### Fixed

- Duplicate rows appearing in task table when sorting with filters applied
- Guild switching no longer flashes back and forth between old and new guild before settling
- Tags now carry over when recurring tasks create their next instance

## [0.23.0] - 2026-02-05

### Added

- Tags view on Documents page for browsing documents by tag
  - Collapsible tag tree with document counts and hierarchical expand/collapse
  - Click to filter by tag, Ctrl/Cmd+Click for multi-select (OR filtering)
  - "Not tagged" filter for documents without any tags
  - Responsive layout: side panel on desktop, collapsible header on mobile
  - Tags view is now the default view mode (Tags / Grid / List)

### Fixed

- Multi-tab guild stability: opening different guilds in separate tabs no longer causes rapid switching or ping-pong loops
  - Removed server-side `active_guild_id` tracking (each tab derives guild from URL)
  - Removed cross-tab localStorage sync that caused cascading re-renders
  - Removed `POST /guilds/{id}/switch` endpoint (no longer needed with guild-scoped URLs)

## [0.22.0] - 2026-02-04

### Added

- Guild-scoped URLs for shareable cross-guild links
  - Routes changed from `/projects/47` to `/g/:guildId/projects/47`
  - Links can be shared directly without losing guild context
  - Old URLs automatically redirect to new format for backward compatibility
  - Cross-guild navigation on My Tasks page works without manual guild switching

## [0.21.0] - 2026-02-04

### Added

- Guild-scoped tags for tasks, projects, and documents
  - Create tags with custom names and colors via TagPicker component
  - Assign multiple tags to tasks, projects, and documents
  - Filter by tags in project tasks view, projects page, and documents page
  - Tags displayed on project cards, document cards, and task table rows
  - Tag browser in sidebar with nested hierarchy support (e.g., "books/fiction")
  - Tag detail page showing all entities with a specific tag
  - Tags preserved when duplicating tasks, projects, or documents
  - Case-insensitive unique names per guild
- Document wikilinks with `[[Document Title]]` syntax
  - Type `[[` in the editor to search for documents in the current initiative
  - Autocomplete shows existing documents, with option to create new ones
  - Resolved links display in blue; unresolved links display in grey/italic
  - Click links to navigate or create documents
  - Backlinks section shows documents that link to the current document
  - Document titles must be unique within each initiative

### Fixed

- Race condition in recording recent project views causing duplicate key errors

## [0.20.1] - 2026-02-03

### Changed

- Initiative settings members table now has separate Name and Email columns
- Removing a member from an initiative now shows a confirmation dialog warning that explicit access to all projects and documents will be removed

### Fixed

- Members table filter input now works correctly
- Users dropdown now refreshes when switching guilds (was showing stale data from previous guild)

## [0.20.0] - 2026-02-03

### Added

- Configurable role permissions per initiative
  - Four permission keys: `docs_enabled`, `projects_enabled`, `create_docs`, `create_projects`
  - Roles tab in Initiative Settings to manage role permissions
  - Create custom roles with configurable permissions
  - Rename and delete custom roles
  - Sidebar hides Docs/Projects based on role permissions
  - Create buttons hidden based on role permissions
  - Built-in PM role has locked permissions; Member role is configurable
  - Does not override DAC for project/document resources (direct links still work with explicit access)
- Document AI Summary feature
  - "Summarize with AI" generates 2-4 paragraph summaries of native documents
  - New side panel with tabs for AI Summary and Comments
  - Panel toggle button in document header
  - Summary persists when switching between tabs
  - Converts Lexical editor content to Markdown for better AI comprehension
- Uploadable file documents (PDF, Word, Excel, PowerPoint, text, HTML)
  - Upload files via "Upload file" tab in create document dialog
  - PDF viewer with zoom controls and continuous page scrolling
  - Office documents show download prompt (browser preview not supported)
  - 50 MB file size limit with client-side validation
- Lazy loading for document detail page (Editor and PDF viewer load on demand)
- Comment editing for authors
  - Users can edit their own comments on tasks and documents
  - Edit button appears next to Reply for author's own comments
  - Inline edit mode with Save/Cancel buttons
  - "(edited)" indicator shows when a comment has been modified

### Changed

- Document comments moved from inline section to side panel
- AI-generated subtasks and descriptions now include initiative and project names for better context
- Only guild admins and initiative project managers can pin/unpin projects
- Pin button is now hidden for users who cannot pin (instead of showing disabled)
- Refactored project access control to discretionary access control (DAC) model
  - Task assignments are automatically removed when a user loses write access (permission removed or downgraded to read)
  - Removed `members_can_write` toggle from projects
  - Added `read` permission level (owner, write, read)
  - Access is now determined solely by explicit permissions in the project_permissions table
  - On project creation, all initiative members are automatically granted read access
  - When a user leaves an initiative, their project permissions are cleaned up automatically
  - When a project owner is removed from an initiative, all initiative PMs get owner access
  - Project settings page now shows a permissions table instead of the old toggle + overrides UI
- Refactored document access control to discretionary access control (DAC) model
  - Added `owner` permission level to documents (owner, write, read)
  - Document creators automatically become owners with full management rights
  - Owners can manage permissions, delete, and duplicate documents without being initiative PMs
  - Added individual member management endpoints (POST/PATCH/DELETE) for document permissions
  - When a document owner is removed from an initiative, all initiative PMs get owner access
  - Document settings page now shows a permissions table instead of the old toggle UI

### Fixed

- Document editor no longer appears blank when collaboration mode is loading
- Collaboration now shows proper status progression: "Connecting..." → "Syncing..." → "Live editing"
- Fixed stuck "Syncing..." spinner after navigating between documents quickly
- Collaboration connection now automatically reconnects when dropped
- Error toast now appears when collaboration fails, with automatic fallback to autosave mode

## [0.19.1] - 2026-01-30

### Fixed

- Task filters now properly reset when navigating between projects

## [0.19.0] - 2026-01-30

### Added

- Guild sidebar context menu (right-click)
  - All members: View initiatives, Copy guild ID, Leave guild
  - Guild admins: View members, Invite members (creates & copies invite link), Create initiative, Guild settings
  - Leave guild checks eligibility (last admin, sole PM of initiatives) before allowing departure
  - Actions automatically switch to the target guild's context when needed

### Changed

- Migrated frontend routing from React Router to TanStack Router
  - Type-safe routing with validated route params and search params
  - Improved React Query integration for data prefetching
- Removed initiative filter from My Tasks page (was showing only active guild's initiatives, making it redundant)

### Fixed

- Switching guilds now properly refreshes project, initiative, and document lists
- Connect and login pages no longer require double-clicking to navigate on mobile
- Live collaboration and real-time updates now work on mobile apps

## [0.18.0] - 2026-01-28

### Added

- Platform admin blocker resolution for user deletion
  - New admin endpoints to delete guilds, promote guild members, and promote initiative members
  - Enhanced deletion eligibility response includes detailed blocker info with promotable members
  - Delete user dialog now shows "Resolve Blockers" step with inline actions
  - Admins can promote another member to guild admin or delete the guild entirely
  - Admins can promote another member to project manager for initiatives
  - Auto-advances to next step when all blockers are resolved
- PostgreSQL Row Level Security (RLS) for guild data isolation
  - Database-level access control ensures users can only access data within their current guild
  - Defense-in-depth protection in addition to application-level access controls
  - Denormalized `guild_id` columns added to all tier 2/3 tables for efficient policy evaluation
  - Automatic triggers maintain guild_id consistency when parent relationships change
  - New `RLSSessionDep` dependency for routes that need database-level access control
  - Admin bypass role (`app_admin`) for migrations and background jobs
- Role-based platform admin system with promote/demote functionality
  - Multiple users can now be platform admins (no longer limited to user ID 1)
  - Platform admins can promote/demote other users via Platform Users settings page
  - Protection against demoting the last platform admin
  - Platform roles and guild roles are now completely independent
  - Guild Users page now manages guild roles separately from platform roles
- `ENABLE_PUBLIC_REGISTRATION` environment variable to control public registration
  - When set to `false`, all new users must register via an invite link
  - Bootstrap (first user) registration is always allowed regardless of setting
  - Landing page and register page adapt UI based on this setting
- Platform admins can now create guilds when `DISABLE_GUILD_CREATION=true`
  - Regular users are still blocked from creating guilds when this flag is enabled
  - The `can_create_guilds` field in user responses now reflects platform admin status

### Changed

- **Docker users**: `DATABASE_URL_ADMIN` environment variable is now required for RLS migrations
  - RLS migrations need superuser privileges to create the `app_admin` role with `BYPASSRLS`
  - Add to your docker-compose: `DATABASE_URL_ADMIN: postgresql+asyncpg://postgres:${POSTGRES_PASSWORD:-initiative}@db:5432/initiative`
  - This URL uses the `postgres` superuser; the regular `DATABASE_URL` continues using the restricted `initiative` user
- Destructive actions now use confirmation dialogs instead of browser alerts

## [0.17.0] - 2026-01-27

### Added

- Switchable color themes with user preference persistence
  - Theme selector in Settings → Interface
  - Three built-in themes: Kobold (default indigo), Displacer (Catppuccin pastels), Strahd (Dracula gothic)
  - Extensible theme system for adding custom themes
  - Themes apply to both light and dark modes
- Spell check suggestions in document editor context menu
  - Right-click on misspelled words to see correction suggestions
  - Uses Typo.js with dictionaries loaded from CDN on first use
  - Works consistently across Chrome, Firefox, and other browsers
- Priority badge is now a clickable dropdown to change task priority inline

### Fixed

- Document page comments now wrap below editor at larger screen widths for better readability
- Past due dates now show green (success) when task is completed instead of always showing red
- Bulk edit dialog now correctly uses "Urgent" priority value instead of invalid "Critical"
- URLs in comments are now clickable and properly wrap instead of overflowing the container
- URLs in task descriptions (markdown) now properly wrap instead of overflowing
- Layout no longer disappears when navigating to lazy-loaded pages (shows spinner in content area)
- Version update popup no longer appears when client version is ahead of server
- Dismissed version popup no longer reappears on page refresh (persisted to localStorage)
- Fixed footer alignment in version update dialog
- Version dialog changelog now renders nested list items

## [0.16.0] - 2026-01-25

### Added

- Live collaborative document editing using Yjs CRDT
  - Multiple users can edit the same document simultaneously in real-time
  - Collaborator presence indicators showing who is currently editing
  - WebSocket-based synchronization with automatic reconnection
  - Graceful fallback to autosave mode if collaboration connection fails
  - New database column `yjs_state` stores collaborative document state

## [0.15.2] - 2026-01-24

### Fixed

- Mobile OIDC deep link handler now works from login page (was only active after authentication)

## [0.15.1] - 2026-01-24

### Added

- Mobile OIDC/SSO login support using deep links
  - OIDC authentication now works on the mobile app
  - Uses Capacitor Browser plugin to open system browser for OAuth flow
  - Custom URL scheme (`initiative://`) handles callback redirect
  - Mobile redirect URI displayed in auth settings page

### Fixed

- Document export now uses document title in filename instead of generic timestamp

## [0.15.0] - 2026-01-23

### Added

- Enabled speech-to-text plugin on document editor. Uses browser speech recognition APIs. Tested working on Chrome and Edge.
- Responsive document editor toolbar
  - Compact overflow menu on screens below 1024px with all formatting options
  - Full inline toolbar on larger screens
- Alignment buttons converted to a dropdown menu for a more compact toolbar

### Fixed

- Speech-to-text now normalizes transcripts across browsers (auto-spacing, auto-capitalization)
- Speech recognition preview bubble no longer hidden behind toolbar
- Android APK version now syncs with main VERSION file (was stuck at 1.0)

## [0.14.1] - 2026-01-23

### Added

- Licensed the project with AGPLv3

### Fixed

- Rolling recurrence now preserves the original due time instead of inheriting the completion timestamp

## [0.14.0] - 2026-01-22

### Added

- Enhanced comments with mentions, threading, and notifications
  - @mention syntax for users (`@[Name](id)`) with autocomplete popup
  - Entity mentions for tasks (`#task[Title](id)`), documents (`#doc[Title](id)`), and projects (`#project[Name](id)`)
  - Threaded replies with visual indentation (max 3 levels)
  - Reply button on each comment with inline reply form
- Comment notifications with intelligent deduplication
  - Notify users when mentioned in comments
  - Notify task assignees when their task is mentioned
  - Notify task assignees when someone comments on their task
  - Notify document authors when someone comments on their document
  - Users already notified via one mechanism won't receive duplicate notifications
- Mentions toggle in user notification settings

### Fixed

- Document editor: heading spacing, horizontal rule spacing, code background, url modal background

## [0.13.0] - 2026-01-21

### Added

- AI Integration with BYOK (Bring Your Own Key) support
  - Hierarchical settings: Platform -> Guild -> User with inheritance and override controls
  - Support for OpenAI, Anthropic, Ollama (local), and custom OpenAI-compatible providers
  - Test connection validates API keys and model names, fetches available models
  - Searchable model combobox with custom model name support
- AI-powered task features (when AI is enabled)
  - Generate description: AI button next to description field auto-generates task descriptions
  - Generate subtasks: AI button in subtasks section suggests actionable subtasks with selection dialog

### Changed

- Anthropic test connection now fetches models dynamically from their API instead of hardcoded list
- Model combobox now fetches available models automatically when opened (improved UX)

## [0.12.5] - 2026-01-20

### Added

- Pull-to-refresh on mobile app to refresh data without reloading the page (My Tasks, Projects, Project Detail, Initiatives)

### Fixed

- Android hardware back button now navigates through router history instead of exiting the app

### Changed

- Inverted app icon. Now when it's themed, its more legible.

## [0.12.4] - 2026-01-18

### Fixed

- FirebaseRuntime plugin now registers before Capacitor bridge initialization

## [0.12.3] - 2026-01-17

### Fixed

- Push notifications now work on self-hosted deployments (fixed FCM config URL)

## [0.12.2] - 2026-01-17

### Fixed

- Task position no longer changes when updating status via dropdown in table view
- Safe area insets now work correctly on Samsung One UI devices

## [0.12.1] - 2026-01-17

### Fixed

- Server crash on startup due to missing request parameter in FCM config endpoint rate limiter

## [0.12.0] - 2026-01-17

### Added

- Push notifications for mobile devices via Firebase Cloud Messaging (FCM)
- Runtime Firebase initialization - no APK rebuild required for self-hosted instances
- Five notification channels for Android: Task Assignments, Initiative Invites, New Projects, User Approvals, and Mentions
- Custom white notification icon for proper Android notification tray display
- Push notification settings in user notification preferences
- Automatic FCM config endpoint for mobile app initialization (`/api/v1/settings/fcm-config`)
- Push token management with automatic cleanup of invalid tokens

## [0.11.1] - 2026-01-16

### Fixed

- Device tokens now display actual device name (e.g., "Jordan's S25 Ultra") instead of generic "Mobile Device"

## [0.11.0] - 2026-01-16

### Added

- Capacitor mobile app support for iOS and Android
- Device authentication tokens for persistent mobile login (never expire)
- Server URL configuration page for connecting to self-hosted instances
- Safe area handling for edge-to-edge display on Android
- Android APK automatically built and attached to GitHub releases
- Device token management in user settings (view and revoke mobile sessions)

### Changed

- Renamed "API Keys" settings tab to "Security" (now includes device management)
- Mobile auth uses device tokens instead of expiring JWTs
- Token storage uses native Preferences API for persistence on mobile

## [0.10.0] - 2026-01-14

### Added

- Task import from external platforms (Todoist CSV, Vikunja JSON, TickTick CSV)
- Import settings page with extensible platform support (Trello, Asana coming soon)
- Section/bucket-to-status mapping with smart suggestions based on names
- Subtask and priority mapping during import

## [0.9.0] - 2026-01-14

### Added

- Task archival feature: archive tasks to hide them from default views
- "Show archived" filter toggle in project task views
- Archive/Unarchive button on task detail page
- "Archive done tasks" bulk action in table view and kanban done columns
- Archive button in bulk selection panel for archiving multiple tasks at once
- Confirmation dialog for archive actions showing task count

## [0.8.0] - 2026-01-13

### Added

- @mention support for tagging initiative members in documents
- Notifications when users are mentioned in documents
- User preference to enable/disable mention notifications
- Autosave for documents with toggle checkbox (enabled by default)

### Changed

- Document editor upgraded to shadcn-editor with improved toolbar and formatting options
- Image uploads now use server-side storage instead of base64 encoding

### Fixed

- WebSocket reconnection storm when token expires (now uses exponential backoff and auto-logout)
- Mentions and emoji picker dropdowns appearing at bottom of editor instead of near cursor

## [0.7.3] - 2026-01-12

### Added

- Rate limiting on all API endpoints (100 requests/minute default)
- Aggressive rate limiting on sensitive auth endpoints (5 requests/15 minutes)
- Rate limiting on OIDC endpoints (login: 20/minute, callback: 5/15 minutes)
- `BEHIND_PROXY` setting to safely trust X-Forwarded-For headers behind reverse proxies

## [0.7.2] - 2026-01-12

### Added

- Version dialog shows last 5 versions with scrolling
- "View all changes" button linking to GitHub CHANGELOG.md
- Changelog endpoint limit parameter (max 10 versions)

### Fixed

- Dialog scrolling with proper flex layout and 80vh height

## [0.7.1] - 2026-01-12

### Fixed

- Changelog not displaying in Docker deployments
- Changelog file now correctly copied into Docker image
- Fixed path resolution for changelog endpoint in Docker environment

## [0.7.0] - 2026-01-12

### Added

- Multiselect filters for task pages
- Users can now select multiple assignees, statuses, priorities, guilds, and initiatives simultaneously
- "Select all" and "Clear all" options in filter dropdowns
- Dropdown shows selected count (e.g., "3 selected")
- Backend now supports array parameters for all task filters using OR logic
- Changelog display in update dialog when new version is available
- Version dialog showing current version, latest version, and full changelog

### Changed

- Default My Tasks status filter now shows backlog, todo, and in_progress (excludes done by default)
- Task filtering moved to server-side for better performance
- Filters use OR logic within each filter type, AND logic between filter types
- Version number interaction changed from hovercard to dialog for both desktop and mobile
- Version dialog now displays full changelog for current version with parsed sections

### Fixed

- Task filters now correctly apply on backend instead of returning all tasks
- TypeScript type error in task query params

## [0.6.4] - 2026-01-11

### Added

- Template selection dropdown for document creation
- "Save as template" toggle when creating documents

### Fixed

- Project documents section now updates properly after attaching/detaching documents
- Cache invalidation issue causing stale document lists

## [0.6.3] - 2026-01-10

### Added

- Initiative collapsed state persistence to localStorage
- Single localStorage key for all initiative states to reduce clutter

### Changed

- Frontend now served by FastAPI instead of nginx for simpler deployment

### Fixed

- TaskAssigneeList component to work with correct TaskAssignee type
- My Tasks page crash from non-array query data

## [0.6.2] - 2026-01-09

### Changed

- Optimized task list endpoints to reduce payload size
- Moved task filtering to backend for better performance

### Fixed

- Backend test suite - 136/142 tests passing (95.8%)
- Task endpoint validation issues
- Test schema mismatches

## [0.6.1] - 2026-01-08

### Fixed

- Double scrollbar issue on ProjectTabsBar
- Improved scrolling aesthetics on Chromium browsers

## [0.6.0] - 2026-01-07

### Added

- User statistics page with metrics and visualizations
- Chart components for data visualization
- Activity tracking and reporting

## [0.5.3] - 2026-01-06

### Fixed

- PWA manifest for Chrome install prompt
- ScrollArea component on tabs bar for better UX

### Added

- Automated release CI workflow

---

## Version Format

Version numbers follow semantic versioning (MAJOR.MINOR.PATCH):

- **MAJOR**: Breaking changes, incompatible API changes
- **MINOR**: New features, backward-compatible additions
- **PATCH**: Bug fixes, backward-compatible fixes

## Categories

- **Added**: New features
- **Changed**: Changes to existing functionality
- **Deprecated**: Soon-to-be-removed features
- **Removed**: Removed features
- **Fixed**: Bug fixes
- **Security**: Security fixes
