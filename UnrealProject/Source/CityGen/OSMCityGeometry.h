// Geometry generation from translated OSM data. Shared by both consumers:
// AOSMCityBuilder (direct/preview path) and the PCG node (UPCGOSMCitySettings),
// so the two can never drift apart geometrically.
#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "OSMCityData.h"
#include "OSMCityGeometry.generated.h"

class UDynamicMesh;

/** Knobs shared by both generation paths. */
USTRUCT(BlueprintType)
struct FOSMBuildOptions
{
	GENERATED_BODY()

	/** Skip footprints whose oriented box is smaller than this, cm^2. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "OSM")
	float MinFootprintAreaCm2 = 60000.f;

	/** Added to every building height, cm. Tuning/debug knob. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "OSM")
	float HeightBiasCm = 0.f;

	/** Roads sit this far above the ground plane to avoid z-fighting, cm. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "OSM")
	float RoadZOffsetCm = 4.f;

	/** Ground slab padding beyond the data bounds, cm. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "OSM")
	float GroundPaddingCm = 5000.f;
};

UCLASS()
class CITYGEN_API UOSMCityGeometry : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:
	/** Extrude every footprint to its height. Returns the number of buildings built. */
	UFUNCTION(BlueprintCallable, Category = "OSM|Geometry")
	static int32 AppendBuildings(UDynamicMesh* TargetMesh, const FOSMCity& City,
		const FOSMBuildOptions& Options);

	/** Flat ribbons along the road centrelines, one quad per segment. */
	UFUNCTION(BlueprintCallable, Category = "OSM|Geometry")
	static int32 AppendRoads(UDynamicMesh* TargetMesh, const FOSMCity& City,
		const FOSMBuildOptions& Options);

	/** A single slab covering the data bounds. */
	UFUNCTION(BlueprintCallable, Category = "OSM|Geometry")
	static bool AppendGround(UDynamicMesh* TargetMesh, const FOSMCity& City,
		const FOSMBuildOptions& Options);
};
