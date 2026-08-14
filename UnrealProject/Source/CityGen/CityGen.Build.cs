using UnrealBuildTool;

public class CityGen : ModuleRules
{
	public CityGen(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		PublicDependencyModuleNames.AddRange(new string[]
		{
			"Core",
			"CoreUObject",
			"Engine",
			"InputCore",
			// JSON translation artefacts produced by pipeline/osm2pcg
			"Json",
			"JsonUtilities",
			// Dynamic mesh generation for footprint extrusion / road ribbons
			"GeometryCore",
			"GeometryFramework",
			"GeometryScriptingCore",
			// PCG graph integration
			"PCG",
			// Dynamic mesh data type + Spawn Dynamic Mesh node used by the graph
			"PCGGeometryScriptInterop",
		});

		PrivateDependencyModuleNames.AddRange(new string[] { });
	}
}
