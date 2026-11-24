<?php

namespace App\Providers;

use App\Models\BatchPlanItem;
use App\Models\ChatMessage;
use App\Models\User;
use App\Services\Agent\AgentClient;
use App\Services\Agent\FakeAgentClient;
use App\Services\Agent\HttpAgentClient;
use App\Services\Llm\LlmClient;
use Illuminate\Http\Client\Factory as HttpFactory;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\Relation;
use Illuminate\Support\ServiceProvider;
use LogicException;

class AppServiceProvider extends ServiceProvider
{
    /**
     * Register any application services.
     */
    public function register(): void
    {
        $this->app->singleton(LlmClient::class, fn ($app) => new LlmClient(
            $app->make(HttpFactory::class),
            (array) config('services.llm', []),
        ));

        $this->app->bind(AgentClient::class, function ($app) {
            $driver = config('agent.driver');

            return match ($driver) {
                'fake' => $app->make(FakeAgentClient::class),
                'http' => new HttpAgentClient(
                    $app->make(HttpFactory::class),
                    (string) config('agent.url'),
                    (string) config('agent.token'),
                    (int) config('agent.timeout', 10),
                ),
                default => throw new LogicException('Driver agen tidak dikenal. Pilihan: fake, http.'),
            };
        });
    }

    /**
     * Bootstrap any application services.
     */
    public function boot(): void
    {
        Relation::enforceMorphMap([
            'user' => User::class,
            'chat_message' => ChatMessage::class,
            'batch_plan_item' => BatchPlanItem::class,
        ]);

        Model::preventLazyLoading(! $this->app->isProduction());
    }
}
