# ECOSTRESS geolocation check

12 scenes: **4 keep**, 4 keep with caution, 3 shifted back, 0 to check by eye, **1 drop**.

Accepted NASA flags: best, good. Offset tolerance: 140 m. Shift correction: on.

| Scene | Time (UTC) | Tile | NASA flag | Measured offset | Decision |
|---|---|---|---|---|---|
| 36879/003 | 2025-01-06 07:52 | 37MAV | best | 22 m | **keep** |
| 37085/008 | 2025-01-19 13:10 | 37MAV | best | 18 m | **keep** |
| 37315/013 | 2025-02-03 09:40 | 37MAV | good | 80 m | **keep** |
| 37534/018 | 2025-02-17 11:05 | 37MAV | suspect | 2701 m | **fixed** |
| 37770/006 | 2025-03-04 15:30 | 37MAV | poor | 5211 m | **fixed** |
| 38029/011 | 2025-03-21 08:20 | 37MAV | good | 50 m | **keep** |
| 38318/016 | 2025-04-08 21:40 | 37MAV | suspect | 71 m | **drop** |
| 39072/004 | 2025-05-27 10:15 | 37MAV | best | 20 m | **caution** |
| 39322/009 | 2025-06-12 12:44 | 37MAV | good | 80 m | **caution** |
| 39522/014 | 2025-06-25 09:02 | 37MAV | not found | 19 m | **caution** |
| 39758/019 | 2025-07-10 14:18 | 37MAV | not found | 1259 m | **fixed** |
| 40112/007 | 2025-08-02 08:47 | 37MAV | best | 25 m | **caution** |

## Reasons

- **orbit 36879 scene 3 tile 37MAV (2025-01-06T07:52)**: NASA flag 'best' (< 50 m); measured offset 22 m (-18 m E, -12 m N) against own water layer (6.6% water), within tolerance.
- **orbit 37085 scene 8 tile 37MAV (2025-01-19T13:10)**: NASA flag 'best' (< 50 m); measured offset 18 m (-14 m E, -11 m N) against own water layer (6.6% water), within tolerance.
- **orbit 37315 scene 13 tile 37MAV (2025-02-03T09:40)**: NASA flag 'good' (about 50 m (corrected from a nearby matched scene)); measured offset 80 m (+63 m E, +51 m N) against own water layer (6.6% water), within tolerance.
- **orbit 37534 scene 18 tile 37MAV (2025-02-17T11:05)**: NASA flag 'suspect' (about 2 to 4 km); measured offset 2701 m (+2298 m E, -1419 m N) against own water layer (6.6% water); shifted copy written.
- **orbit 37770 scene 6 tile 37MAV (2025-03-04T15:30)**: NASA flag 'poor' (up to 7 km); measured offset 5211 m (-4212 m E, +3069 m N) against own water layer (6.6% water); shifted copy written.
- **orbit 38029 scene 11 tile 37MAV (2025-03-21T08:20)**: NASA flag 'good' (about 50 m (corrected from a nearby matched scene)); measured offset 50 m (+47 m E, -18 m N) against own water layer (6.6% water), within tolerance.
- **orbit 38318 scene 16 tile 37MAV (2025-04-08T21:40)**: NASA flag 'suspect' (about 2 to 4 km); measured offset 71 m (+71 m E, -5 m N) against own water layer (6.6% water), within tolerance.
- **orbit 39072 scene 4 tile 37MAV (2025-05-27T10:15)**: NASA flag 'best' (< 50 m); measured offset 20 m (-14 m E, -14 m N) against own water layer (6.6% water), within tolerance; data noisier than expected (15 May to 1 July 2025); NASA says use with caution.
- **orbit 39322 scene 9 tile 37MAV (2025-06-12T12:44)**: NASA flag 'good' (about 50 m (corrected from a nearby matched scene)); measured offset 80 m (-78 m E, -18 m N) against own water layer (6.6% water), within tolerance; data noisier than expected (15 May to 1 July 2025); NASA says use with caution.
- **orbit 39522 scene 14 tile 37MAV (2025-06-25T09:02)**: no geolocation flag found for this scene; measured offset 19 m (-10 m E, -16 m N) against own water layer (6.6% water), within tolerance; data noisier than expected (15 May to 1 July 2025); NASA says use with caution.
- **orbit 39758 scene 19 tile 37MAV (2025-07-10T14:18)**: no geolocation flag found for this scene; measured offset 1259 m (+1101 m E, +611 m N) against own water layer (6.6% water); shifted copy written.
- **orbit 40112 scene 7 tile 37MAV (2025-08-02T08:47)**: NASA flag 'best' (< 50 m); measured offset 25 m (-13 m E, -21 m N) against own water layer (6.6% water), within tolerance; ISS solar array obstructs part of the view (FieldOfViewObstruction).
