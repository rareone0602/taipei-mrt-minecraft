"""A 1:1 Minecraft rebuild of the Taipei Metro.

Layers (dependencies always point inward; an inner layer never imports an outer one):

    domain/          Pure rules: alignment, rail shapes, geometry, tunnel layering,
                     elevation sampling
    ports/           Interfaces the inner layers expose to the outer ones (BlockSink)
    application/     Use cases: write what the domain computes into a BlockSink
    adapters/        External data coming in: OSM, DEM, projection
    infrastructure/  External technical details: Anvil world-save writing, Overpass HTTP

    cli/             Composition root: decides which implementation is used; the only
                     layer that sees everything
    tools/           Verification and inspection (reads the world save back
                     independently and does not trust the generator's own account)
"""
