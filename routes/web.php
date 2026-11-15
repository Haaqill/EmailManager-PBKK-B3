<?php

use App\Http\Controllers\ChatHistoryController;
use App\Http\Controllers\ProfileController;
use Illuminate\Support\Facades\Route;

Route::get('/', function () {
    return view('welcome');
});

Route::get('/dashboard', function () {
    return view('dashboard');
})->middleware(['auth', 'verified'])->name('dashboard');

Route::middleware('auth')->group(function () {
    Route::get('/profile', [ProfileController::class, 'edit'])->name('profile.edit');
    Route::patch('/profile', [ProfileController::class, 'update'])->name('profile.update');
    Route::delete('/profile', [ProfileController::class, 'destroy'])->name('profile.destroy');

    Route::get('/riwayat', [ChatHistoryController::class, 'index'])->name('riwayat.index');
    Route::get('/riwayat/{chatSession}', [ChatHistoryController::class, 'show'])->name('riwayat.show');
});

require __DIR__.'/auth.php';
