// Direct (non-PCG) generator: reads the translated OSM data and builds the whole
// area into dynamic meshes. This is the reference/preview path - it proves the data
// and the geometry maths. The PCG node calls the same UOSMCityGeometry functions.
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "OSMCityData.h"
#include "OSMCityGeometry.h"
#include "OSMCityBuilder.generated.h"

class UDynamicMeshComponent;

UCLASS(BlueprintType, Blueprintable)
class CITYGEN_API AOSMCityBuilder : public AActor
{
	GENERATED_BODY()

public:
	AOSMCityBuilder();

	/** Directory of converter output; relative paths resolve against Content. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "OSM|Source")
	FString CityDataDir = TEXT("Data/City");

	/** Rebuild whenever the actor is moved/edited in the editor. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "OSM|Source")
	bool bBuildOnConstruction = true;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "OSM|Layers")
	bool bGenerateBuildings = true;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "OSM|Layers")
	bool bGenerateRoads = true;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "OSM|Layers")
	bool bGenerateGround = true;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "OSM|Options")
	FOSMBuildOptions BuildOptions;

	/** Counts from the last build, for quick in-editor verification. */
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "OSM|Stats")
	int32 LastBuildingCount = 0;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "OSM|Stats")
	int32 LastRoadCount = 0;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "OSM|Stats")
	FString LastBuildSummary;

	/** Clear + regenerate everything from disk. Idempotent, leaves nothing stale. */
	UFUNCTION(CallInEditor, BlueprintCallable, Category = "OSM")
	void RebuildCity();

	UFUNCTION(CallInEditor, BlueprintCallable, Category = "OSM")
	void ClearCity();

protected:
	virtual void OnConstruction(const FTransform& Transform) override;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "OSM|Components")
	TObjectPtr<UDynamicMeshComponent> BuildingsMesh;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "OSM|Components")
	TObjectPtr<UDynamicMeshComponent> RoadsMesh;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "OSM|Components")
	TObjectPtr<UDynamicMeshComponent> GroundMesh;
};
