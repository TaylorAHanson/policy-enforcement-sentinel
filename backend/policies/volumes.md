# Volume and storage governance

This warns owners when storage is outside Unity Catalog, open to everyone, missing classification, or missing an owner; it does not delete data.

## What it checks

Production data must not be stored in DBFS or local volumes, because those locations do not support Unity Catalog access control or lineage.

Volumes must not grant access to all account users.

Every volume must have a data classification tag.

Every volume must have an identifiable owner.

## Who it affects

The policy applies only to resources identified as storage volumes. The production-location check applies only in production environments; the other checks apply to all in-scope volumes.

## What to do

Move production data into a Unity Catalog-managed location. Remove access for all account users, add the appropriate data classification tag, and record a responsible owner for the volume.
