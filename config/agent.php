<?php

return [
    // Driver "fake" untuk demo offline dan "http" untuk FastAPI.
    'driver' => env('AGENT_DRIVER', 'fake'),
    'url' => env('AGENT_URL', ''),
    'token' => env('AGENT_TOKEN', ''),
    'timeout' => (int) env('AGENT_TIMEOUT', 10),

    // Batas jumlah thread per batch (sama dengan MAX_BATCH di agen Python).
    'max_threads' => 10,

    'fake' => [
        // Lama tiap tahap simulasi (queued, scanning, classifying, drafting, executing).
        'step_seconds' => 2,
    ],
];
