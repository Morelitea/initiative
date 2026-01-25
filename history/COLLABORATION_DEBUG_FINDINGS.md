# Live Collaboration Debug Findings

## Status: In Progress - Blocked

Date: 2026-01-25

## Summary

The live collaboration feature using Yjs and Lexical is partially implemented but has critical sync issues that prevent real-time collaboration from working.

## What Works

1. **WebSocket Connection**: The backend WebSocket endpoint establishes connections
2. **Initial Content Load**: Documents with existing `yjs_state` can load content
3. **UI Indicators**: "Live editing (N)" badge shows correctly
4. **Backend Infrastructure**: pycrdt-based collaboration service handles room management and broadcasting

## What Doesn't Work

1. **Real-time Sync**: Typing on one browser does NOT appear on the other
2. **Lexical → Yjs Sync**: `syncLexicalUpdateToYjs` is called but Yjs document isn't actually modified
3. **First-time Collaboration**: When `yjs_state` is null, content may be lost or not properly bootstrapped
4. **Binding Tree Mismatch**: The @lexical/yjs binding's internal collab node tree doesn't match the Lexical tree

## Root Cause Analysis

### The Core Problem

The @lexical/yjs library is designed for two scenarios:
1. **Yjs has content** → Sync to Lexical (works)
2. **Both empty** → Build up incrementally together (works)

We have a **third scenario** that isn't supported:
3. **Yjs empty, Lexical has content** → Need to bootstrap Yjs from Lexical (FAILS)

### Technical Details

1. **Binding Initialization**:
   - `createBinding()` only creates the root CollabElementNode
   - Child collab nodes are created incrementally during sync
   - But sync requires parent collab nodes to already exist

2. **"Invalid access" Warnings**:
   ```
   Invalid access: Add Yjs type to a document before reading data
   ```
   This indicates Yjs types (XmlElement/XmlText) are being accessed before they're properly added to the document.

3. **"splice: could not find collab element node" Error**:
   - Happens during `syncLexicalUpdateToYjs`
   - A child node's `_parent` is null when it shouldn't be
   - The collab tree wasn't properly built to match Lexical's tree

4. **Sync Flow Issue**:
   - User types → Lexical update event fires
   - `syncLexicalUpdateToYjs` is called
   - Function tries to find parent collab node for dirty elements
   - Parent doesn't exist → sync fails silently or errors

## Attempted Fixes

1. **Using `observeDeep` on sharedRoot** - Events in wrong format
2. **Using `doc.on("update")` with full sync** - Didn't trigger properly
3. **Manual tree initialization** - `IntentionallyMarkedAsDirtyElement` type not exported
4. **Clearing editor then restoring** - `setEditorState` doesn't trigger update listener

## Files Involved

### Frontend
- `frontend/src/hooks/useCollaboration.ts` - Hook managing Yjs doc and provider
- `frontend/src/lib/yjs/CollaborationProvider.ts` - Custom WebSocket provider
- `frontend/src/components/editor-x/plugins/collaboration-plugin.tsx` - Lexical-Yjs binding
- `frontend/src/pages/DocumentDetailPage.tsx` - Integrates collaboration

### Backend
- `backend/app/services/collaboration.py` - Room management, pycrdt integration
- `backend/app/api/v1/endpoints/collaboration.py` - WebSocket endpoint

## Next Steps (Priority Order)

### Option A: Use Official CollaborationPlugin (Recommended)

1. Create a provider adapter that implements the y-websocket `WebsocketProvider` interface
2. Use Lexical's built-in `CollaborationPlugin` component instead of custom low-level code
3. This would leverage Lexical's tested initialization and sync logic

### Option B: Fix Low-Level Integration

1. Before creating binding, manually populate Yjs structure from Lexical:
   - Walk Lexical tree
   - Create corresponding XmlElements/XmlTexts
   - Set correct attributes (`__lexicalType`, `__lexicalKey`, etc.)
2. Then create binding (Yjs already has matching structure)
3. Complex and fragile - needs to match @lexical/yjs internal format exactly

### Option C: Backend Bootstrap

1. When `yjs_state` is null, backend initializes Yjs from document's Lexical JSON
2. Requires replicating @lexical/yjs structure in Python with pycrdt
3. Complex but keeps frontend simpler

### Option D: Accept Limitation

1. For first-time collaboration, clear editor content
2. User must re-enter or paste content
3. Poor UX but technically works
4. Could show warning dialog before entering collab mode

## Recommended Approach

**Option A** is the cleanest solution. The official `CollaborationPlugin` handles:
- Proper binding initialization
- Bootstrap from initial editor state
- Incremental sync in both directions
- Cursor/selection awareness

The work would involve:
1. Modify `CollaborationProvider` to implement the interface that `CollaborationPlugin` expects
2. Replace custom `collaboration-plugin.tsx` with Lexical's `CollaborationPlugin`
3. Test thoroughly

## Console Log Patterns to Watch

When debugging, look for:
```
useCollaboration: Provider effect running        # Effect started
CollaborationProvider: WebSocket opened          # Connection established
CollaborationProvider: Received sync step 2     # Initial state received
CollaborationPlugin: Setting up binding          # Binding created
CollaborationPlugin: hasYjsContent: true/false  # Whether Yjs has content
CollaborationPlugin: Initial sync complete       # Sync ran
CollaborationProvider: Doc updated locally       # Local changes synced to Yjs (MISSING!)
CollaborationProvider: Sending message type: 2   # Update sent to server
CollaborationPlugin: Remote doc update           # Remote changes received
```

The key missing log is `Doc updated locally` - this indicates `syncLexicalUpdateToYjs` isn't actually modifying the Yjs document.

## Test Procedure

1. Open same document in two browsers with different users
2. Both should show "Live editing (2)"
3. Type in one browser
4. Text should appear in other browser
5. Check console for sync messages

## Related Plan

See: `~/.claude/plans/cheeky-knitting-pudding.md` for the original implementation plan.
