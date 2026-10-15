# ECOSTRESS geolocation check

12 scenes: **4 keep**, 3 keep with caution, 0 shifted back, 2 to check by eye, **3 drop**.

Accepted NASA flags: best, good. Offset tolerance: 140 m. Shift correction: off.

| Scene | Time (UTC) | Tile | NASA flag | Measured offset | Decision |
|---|---|---|---|---|---|
| 36879/003 | 2025-01-06 07:52 | 37MAV | best | not measured | **keep** |
| 37085/008 | 2025-01-19 13:10 | 37MAV | best | not measured | **keep** |
| 37315/013 | 2025-02-03 09:40 | 37MAV | good | not measured | **keep** |
| 37534/018 | 2025-02-17 11:05 | 37MAV | suspect | not measured | **drop** |
| 37770/006 | 2025-03-04 15:30 | 37MAV | poor | not measured | **drop** |
| 38029/011 | 2025-03-21 08:20 | 37MAV | good | not measured | **keep** |
| 38318/016 | 2025-04-08 21:40 | 37MAV | suspect | not measured | **drop** |
| 39072/004 | 2025-05-27 10:15 | 37MAV | best | not measured | **caution** |
| 39322/009 | 2025-06-12 12:44 | 37MAV | good | not measured | **caution** |
| 39522/014 | 2025-06-25 09:02 | 37MAV | not found | not measured | **check** |
| 39758/019 | 2025-07-10 14:18 | 37MAV | not found | not measured | **check** |
| 40112/007 | 2025-08-02 08:47 | 37MAV | best | not measured | **caution** |

## Reasons

- **orbit 36879 scene 3 tile 37MAV (2025-01-06T07:52)**: NASA flag 'best' (< 50 m).
- **orbit 37085 scene 8 tile 37MAV (2025-01-19T13:10)**: NASA flag 'best' (< 50 m).
- **orbit 37315 scene 13 tile 37MAV (2025-02-03T09:40)**: NASA flag 'good' (about 50 m (corrected from a nearby matched scene)).
- **orbit 37534 scene 18 tile 37MAV (2025-02-17T11:05)**: NASA flag 'suspect' (about 2 to 4 km).
- **orbit 37770 scene 6 tile 37MAV (2025-03-04T15:30)**: NASA flag 'poor' (up to 7 km).
- **orbit 38029 scene 11 tile 37MAV (2025-03-21T08:20)**: NASA flag 'good' (about 50 m (corrected from a nearby matched scene)).
- **orbit 38318 scene 16 tile 37MAV (2025-04-08T21:40)**: NASA flag 'suspect' (about 2 to 4 km).
- **orbit 39072 scene 4 tile 37MAV (2025-05-27T10:15)**: NASA flag 'best' (< 50 m); data noisier than expected (15 May to 1 July 2025); NASA says use with caution.
- **orbit 39322 scene 9 tile 37MAV (2025-06-12T12:44)**: NASA flag 'good' (about 50 m (corrected from a nearby matched scene)); data noisier than expected (15 May to 1 July 2025); NASA says use with caution.
- **orbit 39522 scene 14 tile 37MAV (2025-06-25T09:02)**: no geolocation flag found for this scene; data noisier than expected (15 May to 1 July 2025); NASA says use with caution.
- **orbit 39758 scene 19 tile 37MAV (2025-07-10T14:18)**: no geolocation flag found for this scene.
- **orbit 40112 scene 7 tile 37MAV (2025-08-02T08:47)**: NASA flag 'best' (< 50 m); ISS solar array obstructs part of the view (FieldOfViewObstruction).
