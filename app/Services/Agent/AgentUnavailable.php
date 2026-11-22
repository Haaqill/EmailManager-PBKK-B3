<?php

namespace App\Services\Agent;

use RuntimeException;

/**
 * Agen tidak bisa dihubungi atau tidak mengenal batch yang diminta.
 * Pesan untuk log; UI menampilkan teks ramah sendiri.
 */
class AgentUnavailable extends RuntimeException
{
}
