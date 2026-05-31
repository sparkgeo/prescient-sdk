package main

import (
	"fmt"

	"github.com/aws/jsii-runtime-go"
	prescientsdk "github.com/sparkgeo/prescient-sdk-go/prescientsdk"
)

func main() {
	defer jsii.Close()

	client := prescientsdk.NewPrescientClient(&prescientsdk.PrescientClientOptions{
		EndpointUrl: jsii.String("https://api.example.com"),
		ClientId:    jsii.String("test-client-id"),
		AuthUrl:     jsii.String("https://login.microsoftonline.com"),
		TenantId:    jsii.String("test-tenant-id"),
	})

	fmt.Println("endpointUrl    :", *client.Settings().EndpointUrl())
	fmt.Println("stacCatalogUrl :", *client.StacCatalogUrl())
	fmt.Println("✓ Go smoke test passed")
}
