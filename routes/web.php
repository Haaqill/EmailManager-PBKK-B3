<?php

use App\Http\Controllers\BatchController;
use App\Http\Controllers\ChatController;
use App\Http\Controllers\ChatHistoryController;
use App\Http\Controllers\ProfileController;
use Illuminate\Support\Facades\Route;

Route::get('/', function () {
    return view('welcome');
});

// Dipertahankan karena alur auth Breeze mengarah ke sini; halaman utama aplikasi adalah chat.
Route::get('/dashboard', function () {
    return redirect()->route('chat');
})->middleware(['auth', 'verified'])->name('dashboard');

Route::middleware(['auth', 'verified'])->group(function () {
    Route::get('/chat', [ChatController::class, 'index'])->name('chat');
    Route::get('/chat/{session}', [ChatController::class, 'show'])
        ->whereNumber('session')
        ->can('view', 'session')
        ->name('chat.show');

    Route::get('/batch', [BatchController::class, 'index'])->name('batch');
    Route::get('/batch/{batch}', [BatchController::class, 'show'])
        ->whereNumber('batch')
        ->can('view', 'batch')
        ->name('batch.show');
});

Route::middleware('auth')->group(function () {
    Route::get('/profile', [ProfileController::class, 'edit'])->name('profile.edit');
    Route::patch('/profile', [ProfileController::class, 'update'])->name('profile.update');
    Route::delete('/profile', [ProfileController::class, 'destroy'])->name('profile.destroy');

    Route::get('/riwayat', [ChatHistoryController::class, 'index'])->name('riwayat.index');
    Route::get('/riwayat/{chatSession}', [ChatHistoryController::class, 'show'])->name('riwayat.show');
});

require __DIR__.'/auth.php';
