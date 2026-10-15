# ECOSTRESS geolocation check

3 scenes: **3 keep**, 0 keep with caution, 0 shifted back, 0 to check by eye, **0 drop**.

Accepted NASA flags: best, good. Offset tolerance: 140 m. Shift correction: off.

| Scene | Time (UTC) | Tile | NASA flag | Measured offset | Decision |
|---|---|---|---|---|---|
| 37534/018 | 2025-02-17 11:05 | 37MAV | not found | 23 m | **keep** |
| 37770/006 | 2025-03-04 15:30 | 37MAV | not found | 16 m | **keep** |
| 39758/019 | 2025-07-10 14:18 | 37MAV | not found | 28 m | **keep** |

## Reasons

- **orbit 37534 scene 18 tile 37MAV (2025-02-17T11:05)**: no geolocation flag found for this scene; measured offset 23 m (-12 m E, -19 m N) against own water layer (6.2% water), within tolerance.
- **orbit 37770 scene 6 tile 37MAV (2025-03-04T15:30)**: no geolocation flag found for this scene; measured offset 16 m (-11 m E, -12 m N) against own water layer (7.5% water), within tolerance.
- **orbit 39758 scene 19 tile 37MAV (2025-07-10T14:18)**: no geolocation flag found for this scene; measured offset 28 m (-20 m E, -20 m N) against own water layer (6.4% water), within tolerance.
