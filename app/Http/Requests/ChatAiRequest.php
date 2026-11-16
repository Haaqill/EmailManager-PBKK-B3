<?php

namespace App\Http\Requests;

use Illuminate\Foundation\Http\FormRequest;

class ChatAiRequest extends FormRequest
{
    public function authorize(): bool
    {
        return true;
    }

    /**
     * @return array<string, mixed>
     */
    public function rules(): array
    {
        return [
            'prompt' => ['required', 'string', 'max:1000'],
            'session_id' => ['nullable', 'integer'],
        ];
    }

    /**
     * @return array<string, string>
     */
    public function messages(): array
    {
        return [
            'prompt.required' => 'Prompt wajib diisi.',
            'prompt.string' => 'Prompt harus berupa teks.',
            'prompt.max' => 'Prompt maksimal 1000 karakter.',
            'session_id.integer' => 'session_id harus berupa angka.',
        ];
    }
}
