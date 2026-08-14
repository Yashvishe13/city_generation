// Direct (non-PCG) generator: reads the translated OSM data and builds the whole
// area into dynamic meshes. This is the reference/preview path - it proves the
// data and the geometry maths, and the PCG graph reuses the same functions.
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "OSMCityData.h"
#include "OSMCityBuilder.generated.h"

class UDynamicMeshComponent;

UCLASS(BlueprintType, Blueprintable)
class CITYGEN_API AOSMCityBuilder : public AActor
{
	GENERATED_BODY()

public:
	AOSMCityBuilder();

	/** Path to city.json; relative paths resolve against the project Content dir. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "OSM|Source")
	FString CityDataPath = TEXT("Data/city.json");

	/** Rebuild whenever the actor is moved/edited in the editor. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "OSM|Source")
	bool bBuildOnConstruction = true;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "OSM|Buildings")
	bool bGenerateBuildings = true;

	/** Skip footprints smaller than this (cm^2 of the oriented box) - OSM noise. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "OSM|Buildings")
	float MinFootprintAreaCm2 = 60000.f;

	/** Extra height added to every building, cm. Debug/tuning knob. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "OSM|Buildings")
	float HeightBiasCm = 0.f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "OSM|Roads")
	bool bGenerateRoads = true;

	/** Roads sit this far above the ground plane to avoid z-fighting, cm. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "OSM|Roads")
	float RoadZOffsetCm = 4.f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "OSM|Ground")
	bool bGenerateGround = true;

	/** Ground slab padding beyond the data bounds, cm. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "OSM|Ground")
	float GroundPaddingCm = 5000.f;

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

	/** Build into an arbitrary mesh - the seam the PCG path will call into. */
	UFUNCTION(BlueprintCallable, Category = "OSM")
	static void AppendBuildings(UDynamicMesh* TargetMesh, const FOSMCity& City,
		float MinAreaCm2, float InHeightBiasCm);

	UFUNCTION(BlueprintCallable, Category = "OSM")
	static void AppendRoads(UDynamicMesh* TargetMesh, const FOSMCity& City, float ZOffsetCm);

	UFUNCTION(BlueprintCallable, Category = "OSM")
	static void AppendGround(UDynamicMesh* TargetMesh, const FOSMCity& City, float PaddingCm);

protected:
	virtual void OnConstruction(const FTransform& Transform) override;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "OSM|Components")
	TObjectPtr<UDynamicMeshComponent> BuildingsMesh;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "OSM|Components")
	TObjectPtr<UDynamicMeshComponent> RoadsMesh;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "OSM|Components")
	TObjectPtr<UDynamicMeshComponent> GroundMesh;
};
