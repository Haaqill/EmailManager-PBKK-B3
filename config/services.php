<?php

return [

    /*
    |--------------------------------------------------------------------------
    | Third Party Services
    |--------------------------------------------------------------------------
    |
    | This file is for storing the credentials for third party services such
    | as Resend, Postmark, AWS, and more. This file provides the de facto
    | location for this type of information, allowing packages to have
    | a conventional file to locate the various service credentials.
    |
    */

    'postmark' => [
        'key' => env('POSTMARK_API_KEY'),
    ],

    'resend' => [
        'key' => env('RESEND_API_KEY'),
    ],

    'ses' => [
        'key' => env('AWS_ACCESS_KEY_ID'),
        'secret' => env('AWS_SECRET_ACCESS_KEY'),
        'region' => env('AWS_DEFAULT_REGION', 'us-east-1'),
    ],

    'slack' => [
        'notifications' => [
            'bot_user_oauth_token' => env('SLACK_BOT_USER_OAUTH_TOKEN'),
            'channel' => env('SLACK_BOT_USER_DEFAULT_CHANNEL'),
        ],
    ],

    'llm' => [
        'providers' => array_values(array_filter(array_map(
            'trim',
            explode(',', (string) env('LLM_PROVIDERS', 'senopati,ollama'))
        ))),
        'ollama' => [
            'base_url' => env('LLM_OLLAMA_URL', 'http://127.0.0.1:11434/v1'),
            'model' => env('LLM_OLLAMA_MODEL', 'qwen3:4b'),
            'api_key' => '',
        ],
        'senopati' => [
            'base_url' => env('LLM_SENOPATI_URL'),
            'model' => env('LLM_SENOPATI_MODEL'),
            'api_key' => env('LLM_SENOPATI_KEY'),
        ],
        'timeout' => (int) env('LLM_TIMEOUT', 60),
        'max_tokens' => (int) env('LLM_MAX_TOKENS', 512),
    ],

];
