#include "CityGeneratorActor.h"

#include "Components/BoxComponent.h"
#include "PCGComponent.h"
#include "PCGGraph.h"

DEFINE_LOG_CATEGORY_STATIC(LogCityGenerator, Log, All);

ACityGeneratorActor::ACityGeneratorActor()
{
	PrimaryActorTick.bCanEverTick = false;

	GenerationBounds = CreateDefaultSubobject<UBoxComponent>(TEXT("GenerationBounds"));
	GenerationBounds->SetBoxExtent(BoundsExtentCm, /*bUpdateOverlaps=*/false);
	GenerationBounds->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	GenerationBounds->SetHiddenInGame(true);
	SetRootComponent(GenerationBounds);

	PCG = CreateDefaultSubobject<UPCGComponent>(TEXT("PCG"));
}

void ACityGeneratorActor::OnConstruction(const FTransform& Transform)
{
	Super::OnConstruction(Transform);

	if (!PCG)
	{
		return;
	}

	if (GenerationBounds)
	{
		GenerationBounds->SetBoxExtent(BoundsExtentCm, /*bUpdateOverlaps=*/false);
	}

	if (CityGraph && PCG->GetGraph() != CityGraph->GetGraph())
	{
		PCG->SetGraph(CityGraph);
	}

	// Only kick generation when nothing has been generated yet: PCG spawns its managed
	// components on this actor, and regenerating unconditionally here would re-enter.
	if (bGenerateOnConstruction && !PCG->bGenerated)
	{
		UE_LOG(LogCityGenerator, Log, TEXT("%s: scheduling PCG generation"), *GetName());
		PCG->Generate(/*bForce=*/false);
	}
}

void ACityGeneratorActor::GenerateCity()
{
	if (!PCG)
	{
		return;
	}
	if (CityGraph && PCG->GetGraph() != CityGraph->GetGraph())
	{
		PCG->SetGraph(CityGraph);
	}
	PCG->Cleanup();
	PCG->Generate(/*bForce=*/true);
}

void ACityGeneratorActor::CleanupCity()
{
	if (PCG)
	{
		PCG->Cleanup();
	}
}
