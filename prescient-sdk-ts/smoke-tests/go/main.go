package main

import (
	"fmt"

	"github.com/aws/jsii-runtime-go"
	prescientsdk "github.com/sparkgeo/prescient-sdk-go/prescientsdk"
)

func main() {
	defer jsii.Close()

	client := prescientsdk.NewPrescientClient(&prescientsdk.PrescientClientOptions{
		EnvFile: jsii.String("/workspace/smoke-tests/config.env"),
	})

	fmt.Println("endpointUrl    :", *client.Settings().EndpointUrl())
	fmt.Println("stacCatalogUrl :", *client.StacCatalogUrl())
	fmt.Println("✓ Go smoke test passed")
}
