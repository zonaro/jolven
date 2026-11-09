# Android library views / console shelf

This OpenEmux-inspired library presentation provides search over Android games, streaming clients and ROMs; console filter; and ROM list, cover and cartridge-label layouts. No emulation engine is embedded.

- Console detection uses the curated Kwiq-inspired extension mapping. Ambiguous ZIP, ISO, BIN, CUE, CHD and related extensions require an explicit platform choice.
- Platform selections and favorites are local and offline. List view and grid views use the same item actions; cover and cartridge label images are different local assets.
- Collections retain stable scoped references and are filtered without duplicating catalog entries.
- This first implementation uses a shrinkwrapped grid and should be performance-tested on real hardware with 1000+ entries before the large-library criterion can be completed.

Remaining #147: persistent view/filter preferences, sorting modes, virtualized large library, gamepad focus restoration, artwork licensing and auto-lookup, batch actions, desktop parity.
