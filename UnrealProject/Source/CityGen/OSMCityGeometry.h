// Geometry generation from a loaded scene. One function per contract primitive, and
// nothing here knows what a building or a road is - only rings, triangles and strips.
#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "OSMCityData.h"
#include "OSMCityGeometry.generated.h"

class UDynamicMesh;

/** Engine-side rendering options. No city semantics belong in here. */
USTRUCT(BlueprintType)
struct FOSMBuildOptions
{
	GENERATED_BODY()

	/**
	 * Optional debug filter, cm^2. Zero by default: which volumes exist is decided by
	 * the pipeline, not at generation time.
	 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "OSM")
	float MinFootprintAreaCm2 = 0.f;

	/** Added to every extrusion, cm. Tuning/debug knob. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "OSM")
	float HeightBiasCm = 0.f;

	/** Ribbons sit this far above the ground plane to avoid z-fighting, cm. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "OSM")
	float RibbonZOffsetCm = 4.f;

	/** Vertical separation per layer step, cm, so a tunnel is not drawn at street level. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "OSM")
	float LayerSpacingCm = 400.f;

	/** Ground slab padding beyond the scene bounds, cm. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "OSM")
	float GroundPaddingCm = 5000.f;
};

UCLASS()
class CITYGEN_API UOSMCityGeometry : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:
	/** Sweep each ring from its base to its top. Returns the number built. */
	UFUNCTION(BlueprintCallable, Category = "OSM|Geometry")
	static int32 AppendExtrudes(UDynamicMesh* TargetMesh, const FOSMScene& Scene,
		const FOSMBuildOptions& Options);

	/** Append indexed triangles verbatim; they are already in world coordinates. */
	UFUNCTION(BlueprintCallable, Category = "OSM|Geometry")
	static int32 AppendMeshes(UDynamicMesh* TargetMesh, const FOSMScene& Scene,
		const FOSMBuildOptions& Options);

	/** Widen each polyline into a flat strip. */
	UFUNCTION(BlueprintCallable, Category = "OSM|Geometry")
	static int32 AppendRibbons(UDynamicMesh* TargetMesh, const FOSMScene& Scene,
		const FOSMBuildOptions& Options);

	/** A single slab covering the scene bounds. */
	UFUNCTION(BlueprintCallable, Category = "OSM|Geometry")
	static bool AppendGround(UDynamicMesh* TargetMesh, const FOSMScene& Scene,
		const FOSMBuildOptions& Options);
};
