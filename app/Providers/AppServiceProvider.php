<?php

namespace App\Providers;

use App\Models\BatchPlanItem;
use App\Models\ChatMessage;
use App\Models\User;
use App\Services\Llm\LlmClient;
use Illuminate\Http\Client\Factory as HttpFactory;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\Relation;
use Illuminate\Support\ServiceProvider;

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
