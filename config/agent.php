<?php

return [
    /*
    | Driver AgentClient: "fake" (data contoh, mode demo). "http" (agen Python lewat
    | FastAPI) belum diimplementasikan; memilihnya melempar pengecualian.
    */
    'driver' => env('AGENT_DRIVER', 'fake'),

    // Batas jumlah thread per batch (sama dengan MAX_BATCH di agen Python).
    'max_threads' => 10,

    'fake' => [
        // Lama tiap tahap simulasi (queued, scanning, classifying, drafting, executing).
        'step_seconds' => 2,
    ],
];
