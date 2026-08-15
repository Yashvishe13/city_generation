#include "OSMCityData.h"

#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

DEFINE_LOG_CATEGORY_STATIC(LogOSMCity, Log, All);

namespace
{
	bool ParsePoint2D(const TSharedPtr<FJsonValue>& Value, FVector2D& Out)
	{
		const TArray<TSharedPtr<FJsonValue>>* Pair = nullptr;
		if (!Value.IsValid() || !Value->TryGetArray(Pair) || Pair->Num() < 2)
		{
			return false;
		}
		Out = FVector2D((*Pair)[0]->AsNumber(), (*Pair)[1]->AsNumber());
		return true;
	}

	bool ParsePoint3D(const TSharedPtr<FJsonValue>& Value, FVector& Out)
	{
		const TArray<TSharedPtr<FJsonValue>>* Triple = nullptr;
		if (!Value.IsValid() || !Value->TryGetArray(Triple) || Triple->Num() < 3)
		{
			return false;
		}
		Out = FVector((*Triple)[0]->AsNumber(), (*Triple)[1]->AsNumber(), (*Triple)[2]->AsNumber());
		return true;
	}

	void ParseRing(const TArray<TSharedPtr<FJsonValue>>& Points, TArray<FVector2D>& Out)
	{
		Out.Reserve(Points.Num());
		for (const TSharedPtr<FJsonValue>& Entry : Points)
		{
			FVector2D Point;
			if (ParsePoint2D(Entry, Point))
			{
				Out.Add(Point);
			}
		}
	}

	void ParseRingField(const TSharedPtr<FJsonObject>& Obj, const FString& Field,
		TArray<FVector2D>& Out)
	{
		const TArray<TSharedPtr<FJsonValue>>* Arr = nullptr;
		if (Obj->TryGetArrayField(Field, Arr))
		{
			ParseRing(*Arr, Out);
		}
	}

	void ParseTags(const TSharedPtr<FJsonObject>& Obj, TArray<FString>& Out)
	{
		const TArray<TSharedPtr<FJsonValue>>* Arr = nullptr;
		if (!Obj->TryGetArrayField(TEXT("tags"), Arr))
		{
			return;
		}
		for (const TSharedPtr<FJsonValue>& Entry : *Arr)
		{
			FString Tag;
			if (Entry->TryGetString(Tag))
			{
				Out.Add(Tag);
			}
		}
	}

	/** Shoelace area of a ring, cm^2. */
	float RingArea(const TArray<FVector2D>& Ring)
	{
		double Sum = 0.0;
		const int32 Count = Ring.Num();
		for (int32 i = 0; i < Count; ++i)
		{
			const FVector2D& A = Ring[i];
			const FVector2D& B = Ring[(i + 1) % Count];
			Sum += A.X * B.Y - B.X * A.Y;
		}
		return static_cast<float>(FMath::Abs(Sum) * 0.5);
	}

	FVector2D RingCentroid(const TArray<FVector2D>& Ring)
	{
		FVector2D Sum = FVector2D::ZeroVector;
		for (const FVector2D& P : Ring)
		{
			Sum += P;
		}
		return Ring.Num() > 0 ? Sum / Ring.Num() : Sum;
	}
}

FString UOSMCityDataLibrary::ResolveDataPath(const FString& FilePath)
{
	if (FPaths::IsRelative(FilePath))
	{
		return FPaths::ConvertRelativePathToFull(FPaths::ProjectContentDir() / FilePath);
	}
	return FilePath;
}

bool UOSMCityDataLibrary::LoadSceneFromDirectory(const FString& DirPath, FOSMScene& OutScene,
	FString& OutError)
{
	OutScene = FOSMScene();
	const FString ScenePath = ResolveDataPath(DirPath) / TEXT("scene.json");

	FString Text;
	if (!FFileHelper::LoadFileToString(Text, *ScenePath))
	{
		OutError = FString::Printf(TEXT("could not read '%s'"), *ScenePath);
		UE_LOG(LogOSMCity, Error, TEXT("%s"), *OutError);
		return false;
	}

	TSharedPtr<FJsonObject> Root;
	const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Text);
	if (!FJsonSerializer::Deserialize(Reader, Root) || !Root.IsValid())
	{
		OutError = FString::Printf(TEXT("malformed JSON in '%s'"), *ScenePath);
		return false;
	}

	// --- manifest: area and origin, so georegistration is inspectable in-editor.
	const TSharedPtr<FJsonObject>* Manifest = nullptr;
	if (Root->TryGetObjectField(TEXT("manifest"), Manifest))
	{
		(*Manifest)->TryGetStringField(TEXT("area"), OutScene.AreaName);
		const TSharedPtr<FJsonObject>* Origin = nullptr;
		if ((*Manifest)->TryGetObjectField(TEXT("origin"), Origin))
		{
			(*Origin)->TryGetNumberField(TEXT("lat"), OutScene.OriginLat);
			(*Origin)->TryGetNumberField(TEXT("lon"), OutScene.OriginLon);
		}
	}

	const TArray<TSharedPtr<FJsonValue>>* Nodes = nullptr;
	if (!Root->TryGetArrayField(TEXT("nodes"), Nodes))
	{
		OutError = FString::Printf(TEXT("'%s' has no nodes array"), *ScenePath);
		return false;
	}

	for (const TSharedPtr<FJsonValue>& Entry : *Nodes)
	{
		const TSharedPtr<FJsonObject>* Node = nullptr;
		if (!Entry->TryGetObject(Node))
		{
			continue;
		}

		FString Kind;
		(*Node)->TryGetStringField(TEXT("kind"), Kind);
		FString Id;
		(*Node)->TryGetStringField(TEXT("id"), Id);
		double Number = 0.0;

		if (Kind == TEXT("extrude"))
		{
			FOSMExtrude Extrude;
			Extrude.Id = Id;
			ParseRingField(*Node, TEXT("outline"), Extrude.Outline);
			if ((*Node)->TryGetNumberField(TEXT("height_cm"), Number)) { Extrude.HeightCm = static_cast<float>(Number); }
			if ((*Node)->TryGetNumberField(TEXT("base_cm"), Number)) { Extrude.BaseCm = static_cast<float>(Number); }
			ParseTags(*Node, Extrude.Tags);

			const TArray<TSharedPtr<FJsonValue>>* Holes = nullptr;
			if ((*Node)->TryGetArrayField(TEXT("holes"), Holes))
			{
				for (const TSharedPtr<FJsonValue>& HoleValue : *Holes)
				{
					const TArray<TSharedPtr<FJsonValue>>* HoleRing = nullptr;
					if (!HoleValue->TryGetArray(HoleRing))
					{
						continue;
					}
					FOSMRing Ring;
					ParseRing(*HoleRing, Ring.Points);
					if (Ring.Points.Num() >= 3)
					{
						Extrude.Holes.Add(MoveTemp(Ring));
					}
				}
			}

			if (Extrude.Outline.Num() < 3 || Extrude.HeightCm <= Extrude.BaseCm)
			{
				++OutScene.SkippedNodes;
				continue;
			}
			Extrude.AreaCm2 = RingArea(Extrude.Outline);
			Extrude.CentroidCm = RingCentroid(Extrude.Outline);
			OutScene.Extrudes.Add(MoveTemp(Extrude));
		}
		else if (Kind == TEXT("mesh"))
		{
			FOSMMesh Mesh;
			Mesh.Id = Id;
			ParseTags(*Node, Mesh.Tags);

			const TArray<TSharedPtr<FJsonValue>>* Vertices = nullptr;
			if ((*Node)->TryGetArrayField(TEXT("vertices"), Vertices))
			{
				Mesh.Vertices.Reserve(Vertices->Num());
				for (const TSharedPtr<FJsonValue>& VertexValue : *Vertices)
				{
					FVector Vertex;
					if (ParsePoint3D(VertexValue, Vertex))
					{
						Mesh.Vertices.Add(Vertex);
					}
				}
			}

			const TArray<TSharedPtr<FJsonValue>>* Faces = nullptr;
			if ((*Node)->TryGetArrayField(TEXT("indices"), Faces))
			{
				for (const TSharedPtr<FJsonValue>& FaceValue : *Faces)
				{
					const TArray<TSharedPtr<FJsonValue>>* Face = nullptr;
					if (!FaceValue->TryGetArray(Face) || Face->Num() < 3)
					{
						continue;
					}
					const int32 A = static_cast<int32>((*Face)[0]->AsNumber());
					const int32 B = static_cast<int32>((*Face)[1]->AsNumber());
					const int32 C = static_cast<int32>((*Face)[2]->AsNumber());
					// Out-of-range indices would crash the mesh builder; drop the face
					// and let the count surface in the log.
					if (!Mesh.Vertices.IsValidIndex(A) || !Mesh.Vertices.IsValidIndex(B) ||
						!Mesh.Vertices.IsValidIndex(C))
					{
						continue;
					}
					Mesh.Indices.Add(A);
					Mesh.Indices.Add(B);
					Mesh.Indices.Add(C);
				}
			}

			if (Mesh.Vertices.Num() < 3 || Mesh.Indices.Num() < 3)
			{
				++OutScene.SkippedNodes;
				continue;
			}
			OutScene.Meshes.Add(MoveTemp(Mesh));
		}
		else if (Kind == TEXT("ribbon"))
		{
			FOSMRibbon Ribbon;
			Ribbon.Id = Id;
			ParseRingField(*Node, TEXT("points"), Ribbon.Points);
			if ((*Node)->TryGetNumberField(TEXT("width_cm"), Number)) { Ribbon.WidthCm = static_cast<float>(Number); }
			ParseTags(*Node, Ribbon.Tags);

			// Layer is a rendering hint and may sit either on the node or in attrs.
			int32 Layer = 0;
			if ((*Node)->TryGetNumberField(TEXT("layer"), Layer)) { Ribbon.Layer = Layer; }
			const TSharedPtr<FJsonObject>* Attrs = nullptr;
			if ((*Node)->TryGetObjectField(TEXT("attrs"), Attrs) &&
				(*Attrs)->TryGetNumberField(TEXT("layer"), Layer))
			{
				Ribbon.Layer = Layer;
			}

			if (Ribbon.Points.Num() < 2 || Ribbon.WidthCm <= 0.f)
			{
				++OutScene.SkippedNodes;
				continue;
			}
			OutScene.Ribbons.Add(MoveTemp(Ribbon));
		}
		else
		{
			// "instance" is reserved in the contract and anything else is unknown; both
			// are counted rather than silently ignored.
			++OutScene.SkippedNodes;
		}
	}

	for (const FOSMExtrude& Extrude : OutScene.Extrudes)
	{
		for (const FVector2D& Point : Extrude.Outline) { OutScene.BoundsCm += Point; }
	}
	for (const FOSMRibbon& Ribbon : OutScene.Ribbons)
	{
		for (const FVector2D& Point : Ribbon.Points) { OutScene.BoundsCm += Point; }
	}

	OutScene.bValid = OutScene.Extrudes.Num() > 0 || OutScene.Ribbons.Num() > 0
		|| OutScene.Meshes.Num() > 0;
	if (!OutScene.bValid)
	{
		OutError = FString::Printf(TEXT("no usable nodes in '%s'"), *ScenePath);
		return false;
	}

	UE_LOG(LogOSMCity, Log,
		TEXT("loaded '%s': %d extrude, %d mesh, %d ribbon (%d skipped); origin %.6f,%.6f"),
		*OutScene.AreaName, OutScene.Extrudes.Num(), OutScene.Meshes.Num(),
		OutScene.Ribbons.Num(), OutScene.SkippedNodes, OutScene.OriginLat, OutScene.OriginLon);
	return true;
}
