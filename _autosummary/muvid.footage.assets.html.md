# muvid.footage.assets

Bind an asset that is already in one of the caller’s projects into another (muvid#22).

A song or a clip is identified by the SHA-256 of its bytes — the `asset_id` a
`set_song` / `add_footage` reply returns (it equals `artifact_id` in a hosted
project’s catalog). Handing that id to `set_song(asset_id=...)` or
`add_footage(asset_id=...)` takes the file from where it already is, with no network
fetch, and the new project’s copy is a HARDLINK of it (`
replace_file()` `link=True`): the same asset bound to two projects is stored once. Nothing
ever writes into a stored media file in place (every rewrite is a new inode), so two
projects sharing one inode cannot change each other’s bytes, and removing a clip from one
project leaves the other’s.

*Where* an asset is looked for is a seam, [`register_asset_resolver()`](#muvid.footage.assets.register_asset_resolver) — the house
idiom (`register_visual`, `register_aligner`): a resolver is
`(email, asset_id, kind) -> Path | None`, tried in order. The default, [`own_projects()`](#muvid.footage.assets.own_projects),
searches the caller’s own footage projects (muvid’s and a host’s); a library that holds
assets outside any project (braidio’s, muvid#7) registers its own and `muvid` needs no
import of it.

Only an asset whose hash was recorded is found: a clip’s `hash` is recorded when it is
added (and by the first filmstrip or beat measurement of an older one), a song’s
`song_hash` always. Never hashed on a lookup — that would read every file of every
project of the caller.

### Module Attributes

| [`AssetResolver`](#muvid.footage.assets.AssetResolver)   | `(email, asset_id, kind) -> Asset | None`; `kind` is `"audio"` (a song) or `"video"` (a clip).   |
|------------------------------------------------------------------|--------------------------------------------------------------------------------------------------|
| [`ASSET_KINDS`](#muvid.footage.assets.ASSET_KINDS)     | The kinds an asset can be bound as, each with the sentence naming it in a refusal.               |

### Functions

| [`own_projects`](#muvid.footage.assets.own_projects)(email, asset_id, kind)            | The default resolver: the caller's own footage projects, muvid's drawer then a host's, by the hashes their manifests recorded.   |
|-------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------|
| [`register_asset_resolver`](#muvid.footage.assets.register_asset_resolver)(resolver, \*[, first]) | Add `resolver` to the ones [`resolve_asset()`](#muvid.footage.assets.resolve_asset) tries (last, or `first`).            |
| [`resolve_asset`](#muvid.footage.assets.resolve_asset)(email, asset_id, \*, kind)       | The asset `asset_id` as `kind` for this caller; `FootageError` when no resolver finds it.                                        |

### Classes

| [`Asset`](#muvid.footage.assets.Asset)(path[, name, duration_s, linkable])   | A stored asset a resolver found: the file and what its owner already measured, so binding it re-probes nothing it was told.   |
|----------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------|

### muvid.footage.assets.ASSET_KINDS *= {'audio': 'song', 'video': 'video'}*

The kinds an asset can be bound as, each with the sentence naming it in a refusal.

### *class* muvid.footage.assets.Asset(path, name='', duration_s=None, linkable=False)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A stored asset a resolver found: the file and what its owner already measured, so
binding it re-probes nothing it was told.

`linkable` says whether the new project may share the file’s inode (a hardlink).
It is true only for a file muvid itself stores and never writes in place; a library
outside muvid’s trust (muvid#7) is copied, because a shared inode would let a change
out there rewrite the bytes under this project’s content hash.

### muvid.footage.assets.AssetResolver

`(email, asset_id, kind) -> Asset | None`; `kind` is `"audio"` (a song) or
`"video"` (a clip). A resolver IS the authorization boundary: it must find only what
`email` owns, and answer `None` (never raise) for anything else, so a refusal says
nothing about whose asset exists.

alias of `Callable`[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`Asset`](#muvid.footage.assets.Asset) | [`None`](https://docs.python.org/3/builtins/constants.html#None)]

### muvid.footage.assets.own_projects(email, asset_id, kind)

The default resolver: the caller’s own footage projects, muvid’s drawer then a
host’s, by the hashes their manifests recorded. Their files are muvid’s own, so they
are `linkable`.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Asset`](#muvid.footage.assets.Asset)]

### muvid.footage.assets.register_asset_resolver(resolver, , first=False)

Add `resolver` to the ones [`resolve_asset()`](#muvid.footage.assets.resolve_asset) tries (last, or `first`).
Registering the same callable twice is a no-op.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### muvid.footage.assets.resolve_asset(email, asset_id, , kind)

The asset `asset_id` as `kind` for this caller; `FootageError` when
no resolver finds it. The refusal does not say whose project holds it, or whether
another caller’s does (the existence of someone else’s asset is not the caller’s to
learn).

* **Return type:**
  [`Asset`](#muvid.footage.assets.Asset)
