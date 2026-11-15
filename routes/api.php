<?php

use App\Http\Controllers\Api\ChatAiController;
use App\Http\Controllers\Api\ChatAiStreamController;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Route;

Route::get('/user', function (Request $request) {
    return $request->user();
})->middleware('auth:sanctum');

Route::middleware(['auth:sanctum', 'throttle:10,1'])->group(function () {
    Route::post('/chat-ai', ChatAiController::class)->name('api.chat-ai');
    Route::post('/chat-ai/stream', ChatAiStreamController::class)->name('api.chat-ai.stream');
});
