// Host actor for the PCG city graph. BP_CityGenerator derives from this.
//
// PCG's editor workflow normally needs a manual Generate press; this actor triggers
// generation from its construction script instead, so opening CityLevel (or moving /
// editing the actor) rebuilds the city with no manual step. Generation stays PCG's
// job - the actor only assigns the graph and kicks the component.
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "CityGeneratorActor.generated.h"

class UBoxComponent;
class UPCGComponent;
class UPCGGraphInterface;

UCLASS(BlueprintType, Blueprintable)
class CITYGEN_API ACityGeneratorActor : public AActor
{
	GENERATED_BODY()

public:
	ACityGeneratorActor();

	/** The PCG graph to run, normally /Game/PCG/PCG_City. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "City")
	TObjectPtr<UPCGGraphInterface> CityGraph;

	/** Generate from the construction script when the graph has not run yet. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "City")
	bool bGenerateOnConstruction = true;

	/**
	 * Half-extent of the generation volume, cm. A PCGComponent is only registered if
	 * its actor has valid bounds, so the box must enclose the translated area.
	 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "City")
	FVector BoundsExtentCm = FVector(100000.0, 100000.0, 50000.0);

	/** Force a full regenerate (used after re-translating the OSM data). */
	UFUNCTION(CallInEditor, BlueprintCallable, Category = "City")
	void GenerateCity();

	/** Remove everything PCG generated for this actor. */
	UFUNCTION(CallInEditor, BlueprintCallable, Category = "City")
	void CleanupCity();

	UPCGComponent* GetPCGComponent() const { return PCG; }

protected:
	virtual void OnConstruction(const FTransform& Transform) override;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "City")
	TObjectPtr<UPCGComponent> PCG;

	/** Root box that gives the PCG component its bounds. */
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "City")
	TObjectPtr<UBoxComponent> GenerationBounds;
};
