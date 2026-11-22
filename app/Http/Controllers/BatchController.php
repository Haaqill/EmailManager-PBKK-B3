<?php

namespace App\Http\Controllers;

use App\Models\Batch;
use Illuminate\View\View;

/**
 * Halaman Batch. Isinya komponen Livewire BatchIndex dan BatchRun;
 * otorisasi rute batch.show lewat middleware can:view (BatchPolicy).
 */
class BatchController extends Controller
{
    public function index(): View
    {
        return view('batch.index');
    }

    public function show(Batch $batch): View
    {
        return view('batch.show', ['batch' => $batch]);
    }
}
